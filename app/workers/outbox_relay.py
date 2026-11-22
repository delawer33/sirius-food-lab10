"""
Релей Transactional Outbox: переносит события из таблицы outbox в RabbitMQ.

    python -m app.workers.outbox_relay

Цикл: взять неопубликованные строки (FOR UPDATE SKIP LOCKED — два релея не
возьмут одну строку), опубликовать с подтверждением брокера, проставить
published_at, commit. Брокер недоступен — строки ждут, релей переподключается.

Гарантия at-least-once: если релей упал между публикацией и commit, событие
уйдёт второй раз с тем же event_id, consumer'ы его отбросят.

Каждое событие публикуется в контексте запроса, который его породил:
correlation_id и traceparent берутся из строки outbox, span публикации —
дочерний к span'у HTTP-запроса.
"""
import asyncio
import json

import aio_pika
import structlog
from opentelemetry.trace import SpanKind
from sqlalchemy import func
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
import observability
from app.database import SessionLocal, engine
from app.models import OutboxEvent
from messaging.consumer import describe, echo
from messaging.publisher import publish
from messaging.topology import declare_all, declare_exchanges
from observability import tracing
from observability.metrics import OUTBOX_PENDING

TAG = "Outbox"
RECONNECT_DELAY = 2.0


def pending_count(session_factory: sessionmaker) -> int:
    with session_factory() as db:
        return db.query(func.count(OutboxEvent.id)).filter(OutboxEvent.published_at.is_(None)).scalar()


async def publish_batch(exchange, session_factory: sessionmaker, limit: int = 100) -> int:
    """Публикует до limit событий по порядку. Возвращает, сколько опубликовано."""
    with session_factory() as db:
        rows = (
            db.query(OutboxEvent)
            .filter(OutboxEvent.published_at.is_(None))
            .order_by(OutboxEvent.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
            .all()
        )
        for row in rows:
            payload = json.loads(row.payload)
            row.attempts += 1
            with (
                structlog.contextvars.bound_contextvars(
                    correlation_id=row.correlation_id, order_id=payload.get("order_id"), event_id=row.event_id
                ),
                tracing.tracer.start_as_current_span(
                    f"{row.routing_key} publish",
                    context=tracing.extract(json.loads(row.trace_context or "{}")),
                    kind=SpanKind.PRODUCER,
                    attributes={"messaging.system": "rabbitmq", "outbox_id": row.id,
                                "correlation_id": row.correlation_id or ""},
                ),
            ):
                try:
                    await publish(exchange, row.routing_key, payload)
                except Exception as error:
                    # Уже опубликованные в этой пачке помечены, эта — нет.
                    row.last_error = describe(error)[:500]
                    db.commit()
                    raise
                # Время БД, как у created_at.
                row.published_at = func.now()
                echo(TAG, "event_published", routing_key=row.routing_key, outbox_id=row.id)
        db.commit()
        return len(rows)


async def relay_forever(url: str, session_factory: sessionmaker = SessionLocal,
                        interval: float = settings.OUTBOX_POLL_INTERVAL) -> None:
    while True:
        try:
            connection = await aio_pika.connect(url)
        except (aio_pika.exceptions.AMQPConnectionError, OSError) as error:
            try:
                waiting = pending_count(session_factory)
            except OperationalError:
                waiting = "?"
            echo(TAG, f"RabbitMQ недоступен ({type(error).__name__}); в outbox ждут {waiting}; "
                      f"повтор через {RECONNECT_DELAY:g} с")
            await asyncio.sleep(RECONNECT_DELAY)
            continue

        echo(TAG, f"Подключился к RabbitMQ; в outbox ждут {pending_count(session_factory)}")
        try:
            async with connection:
                channel = await connection.channel()
                exchange, _ = await declare_exchanges(channel)
                # Очереди объявлены заранее: событие не пропадёт, даже если
                # consumer ещё не запущен — оно подождёт в его очереди.
                await declare_all(channel)
                while True:
                    try:
                        sent = await publish_batch(exchange, session_factory)
                    except OperationalError as error:
                        echo(TAG, f"БД недоступна: {describe(error)}")
                        sent = 0
                        await asyncio.sleep(RECONNECT_DELAY)
                    if not sent:
                        await asyncio.sleep(interval)
        except Exception as error:
            # Обрыв проявляется по-разному: ConnectionClosed, ChannelInvalidStateError,
            # ConnectionResetError. Любой сбой — переподключиться, строки ждут в outbox.
            echo(TAG, f"Связь с RabbitMQ потеряна ({describe(error)}); переподключаюсь")
            await asyncio.sleep(RECONNECT_DELAY)


def watch_pending(session_factory: sessionmaker) -> None:
    """Gauge считается при каждом опросе Prometheus, а не в цикле релея."""
    def count() -> float:
        try:
            return pending_count(session_factory)
        except Exception:
            return float("nan")

    OUTBOX_PENDING.set_function(count)


def main() -> None:
    observability.setup("outbox-relay")
    tracing.instrument_engine(engine)
    watch_pending(SessionLocal)
    echo(TAG, f"Релей запущен, опрос outbox каждые {settings.OUTBOX_POLL_INTERVAL:g} с")
    asyncio.run(relay_forever(settings.RABBITMQ_URL))


if __name__ == "__main__":
    main()
