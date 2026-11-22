"""
Цикл consumer'а: разбор сообщения, вызов обработчика, подтверждение, повторы и DLQ.

Обработчик — обычная синхронная функция (routing_key, payload) -> Outcome.
Она работает с БД через SQLAlchemy, поэтому выполняется в отдельном потоке:
event loop в это время отвечает брокеру на heartbeat.

Что происходит с сообщением:
- обработчик отработал         -> публикуем его события, затем ack;
- не JSON или нет event_id      -> reject без повтора, сразу в DLQ: повтор не поможет;
- обработчик бросил исключение  -> nack с возвратом в очередь, на попытке MAX_ATTEMPTS — в DLQ;
- consumer упал, не ответив     -> брокер сам вернёт сообщение в очередь (at-least-once).

Наблюдаемость: X-Correlation-ID из заголовков попадает в contextvars логов
(нет заголовка — новый ID), traceparent — родитель span'а обработки. Обработчик
работает в потоке через asyncio.to_thread, контекст копируется туда же.
"""
import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import aio_pika
import sentry_sdk
import structlog
from opentelemetry.trace import SpanKind, Status, StatusCode

from messaging.publisher import publish
from observability import correlation
from observability.metrics import EVENT_DURATION, EVENTS_CONSUMED
from observability.tracing import extract, tracer
from messaging.topology import MAX_ATTEMPTS, QueueSpec, declare_exchanges, declare_queue

REQUIRED_FIELDS = ("event_id", "order_id")


logger = structlog.get_logger()


@dataclass
class Outcome:
    """
    Итог обработки: строка для человека, события, которые надо опубликовать,
    и имя события лога (поле message), по которому логи удобно фильтровать.
    """

    log: str
    publish: list[tuple[str, dict]] = field(default_factory=list)
    event: str = "event_processed"


Handler = Callable[[str, dict], Outcome]


class BadMessage(Exception):
    """Сообщение нельзя обработать никогда: не JSON, нет обязательных полей."""


def echo(tag: str, text: str, **fields) -> None:
    """Строка для человека в поле message, tag — в component, остальное — поля JSON."""
    logger.info(text, component=tag, **fields)


def short(event_id: str) -> str:
    return str(event_id)[:8]


def describe(error: Exception) -> str:
    """Одна строка про ошибку: у SQLAlchemy настоящая причина в error.orig."""
    cause = getattr(error, "orig", None) or error
    lines = str(cause).strip().splitlines()
    return f"{type(cause).__name__}: {lines[0] if lines else ''}"


def parse(body: bytes) -> dict:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise BadMessage(f"не JSON: {body[:40]!r}") from None
    if not isinstance(payload, dict):
        raise BadMessage("ожидался JSON-объект")
    missing = [name for name in REQUIRED_FIELDS if name not in payload]
    if missing:
        raise BadMessage(f"нет полей {', '.join(missing)}")
    if not isinstance(payload["order_id"], int):
        raise BadMessage("order_id не число")
    return payload


def attempt_of(message: aio_pika.abc.AbstractIncomingMessage) -> int:
    """Номер попытки: quorum-очередь пишет, сколько раз сообщение уже доставляли."""
    return int((message.headers or {}).get("x-delivery-count", 0)) + 1


async def handle(message, spec: QueueSpec, tag: str, handler: Handler, exchange, retry_delay: float) -> None:
    headers = message.headers or {}
    correlation_id = correlation.accept(headers.get(correlation.HEADER))
    with (
        structlog.contextvars.bound_contextvars(
            correlation_id=correlation_id, component=tag, queue=spec.name, routing_key=message.routing_key
        ),
        tracer.start_as_current_span(
            f"{spec.name} process",
            context=extract(headers),
            kind=SpanKind.CONSUMER,
            attributes={
                "messaging.system": "rabbitmq",
                "messaging.destination.name": spec.name,
                "messaging.rabbitmq.destination.routing_key": message.routing_key or "",
                "correlation_id": correlation_id,
            },
        ) as span,
    ):
        started = time.perf_counter()
        result = await _handle(message, spec, handler, exchange, retry_delay, span)
        EVENTS_CONSUMED.labels(queue=spec.name, result=result).inc()
        EVENT_DURATION.labels(queue=spec.name).observe(time.perf_counter() - started)


async def _handle(message, spec: QueueSpec, handler: Handler, exchange, retry_delay: float, span) -> str:
    """Обрабатывает сообщение и возвращает исход для метрики: ok, retry, dlq, bad."""
    key = message.routing_key
    try:
        payload = parse(message.body)
    except BadMessage as error:
        logger.warning("message_rejected", reason=str(error), dlq=spec.dlq)
        span.set_status(Status(StatusCode.ERROR, str(error)))
        await message.reject(requeue=False)
        return "bad"

    attempt = attempt_of(message)
    with structlog.contextvars.bound_contextvars(order_id=payload["order_id"], event_id=payload["event_id"]):
        span.set_attribute("order_id", payload["order_id"])
        span.set_attribute("event_id", str(payload["event_id"]))
        try:
            outcome = await asyncio.to_thread(handler, key, payload)
            for routing_key, event in outcome.publish:
                await publish(exchange, routing_key, event)
        except Exception as error:
            span.record_exception(error)
            span.set_status(Status(StatusCode.ERROR, describe(error)))
            fields = {"attempt": attempt, "max_attempts": MAX_ATTEMPTS, "error": describe(error)}
            if attempt >= MAX_ATTEMPTS:
                logger.error("event_dead_lettered", **fields, dlq=spec.dlq)
                # В Sentry — только окончательный отказ, не каждая попытка.
                sentry_sdk.capture_exception(error)
                await message.reject(requeue=False)
                return "dlq"
            logger.warning("event_retry", **fields)
            await asyncio.sleep(retry_delay)
            await message.nack(requeue=True)
            return "retry"

        logger.info(outcome.event, result=outcome.log, attempt=attempt)
        for routing_key, event in outcome.publish:
            logger.info("event_published", published_key=routing_key, published_event_id=event["event_id"])
        await message.ack()
        return "ok"


async def consume(url: str, spec: QueueSpec, tag: str, handler: Handler, retry_delay: float = 1.0) -> None:
    """Слушает очередь spec, пока задачу не отменят."""
    connection = await aio_pika.connect_robust(url)
    async with connection:
        channel = await connection.channel()
        # Не больше 10 неподтверждённых сообщений на consumer'а.
        await channel.set_qos(prefetch_count=10)
        queue = await declare_queue(channel, spec)
        exchange, _ = await declare_exchanges(channel)
        echo(tag, f"Слушаю {spec.name} ← {', '.join(spec.bindings)}; битые → {spec.dlq}",
             queue=spec.name, bindings=list(spec.bindings), dlq=spec.dlq)
        async with queue.iterator() as messages:
            async for message in messages:
                await handle(message, spec, tag, handler, exchange, retry_delay)
