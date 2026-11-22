"""Публикация события в exchange."""
import json

import aio_pika

from observability import correlation, tracing
from observability.metrics import EVENTS_PUBLISHED


async def publish(exchange: aio_pika.abc.AbstractExchange, routing_key: str, payload: dict) -> None:
    """
    Канал aio-pika открыт с publisher confirms: вызов вернётся, когда брокер
    записал сообщение. mandatory: если ни одна очередь не привязана к ключу,
    публикация падает, а не теряет событие молча.

    В заголовки уходят X-Correlation-ID и traceparent из текущего контекста:
    consumer продолжит ту же операцию и тот же трейс.
    """
    headers = {}
    if correlation_id := correlation.current():
        headers[correlation.HEADER] = correlation_id
    tracing.inject(headers)
    message = aio_pika.Message(
        body=json.dumps(payload, ensure_ascii=False).encode(),
        content_type="application/json",
        message_id=str(payload["event_id"]),
        headers=headers,
        # Сообщение пишется на диск и переживает перезапуск брокера.
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
    )
    await exchange.publish(message, routing_key=routing_key, mandatory=True)
    EVENTS_PUBLISHED.labels(routing_key=routing_key).inc()
