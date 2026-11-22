"""
Инфраструктурный модуль для работы с RabbitMQ: подключение и разовая
публикация события.

Заказы не публикуют события сами: они пишут их в outbox, а в брокер их
переносит app/workers/outbox_relay.py. publish_event нужен скриптам.
"""
import aio_pika

from app.core.config import settings
from messaging.publisher import publish
from messaging.topology import declare_all, declare_exchanges


async def get_connection() -> aio_pika.abc.AbstractRobustConnection:
    """Robust — автоматически переподключается после обрыва."""
    return await aio_pika.connect_robust(settings.RABBITMQ_URL)


async def publish_event(routing_key: str, payload: dict) -> None:
    """Публикует событие в exchange sirius_events, например с ключом order.paid."""
    connection = await get_connection()
    async with connection:
        channel = await connection.channel()
        exchange, _ = await declare_exchanges(channel)
        await declare_all(channel)
        await publish(exchange, routing_key, payload)
