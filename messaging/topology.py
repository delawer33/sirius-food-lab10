"""
Топология RabbitMQ проекта.

    sirius_events (topic) ──order.paid──────► kitchen_queue     ─┐
                          ──order.cancelled─► kitchen_queue      │ отказ
                          ──order.paid──────► delivery_queue     ├─────► dlx_exchange (direct) ──► *_dlq
                          ──delivery.failed─► order_saga_queue   │
                          ──#───────────────► event_log_queue   ─┘

Объявление идемпотентно: каждый процесс при старте объявляет то, что ему
нужно, и неважно, кто стартовал первым. Аргументы очереди менять нельзя:
RabbitMQ ответит PRECONDITION_FAILED, очередь придётся удалить.
"""
from dataclasses import dataclass

import aio_pika
from aio_pika import ExchangeType

EXCHANGE = "sirius_events"
DLX = "dlx_exchange"

# Сколько раз consumer пробует обработать сообщение, прежде чем отправить его в DLQ.
MAX_ATTEMPTS = 3
# Страховка брокера: если consumer падает целиком, не успев ответить,
# сообщение всё равно уйдёт в DLQ после стольких доставок.
DELIVERY_LIMIT = 5


@dataclass(frozen=True)
class QueueSpec:
    name: str
    bindings: tuple[str, ...]

    @property
    def short(self) -> str:
        return self.name.removesuffix("_queue")

    @property
    def dlq(self) -> str:
        return f"{self.short}_dlq"

    @property
    def dlq_key(self) -> str:
        return f"{self.short}.dlq"


KITCHEN = QueueSpec("kitchen_queue", ("order.paid", "order.cancelled"))
DELIVERY = QueueSpec("delivery_queue", ("order.paid",))
SAGA = QueueSpec("order_saga_queue", ("delivery.failed",))
EVENT_LOG = QueueSpec("event_log_queue", ("#",))
ALL_QUEUES = (KITCHEN, DELIVERY, SAGA, EVENT_LOG)


async def declare_exchanges(channel: aio_pika.abc.AbstractChannel):
    """exchange событий и DLX. Оба durable: переживают перезапуск брокера."""
    exchange = await channel.declare_exchange(EXCHANGE, ExchangeType.TOPIC, durable=True)
    dlx = await channel.declare_exchange(DLX, ExchangeType.DIRECT, durable=True)
    return exchange, dlx


async def declare_queue(channel: aio_pika.abc.AbstractChannel, spec: QueueSpec):
    """Очередь consumer'а, её DLQ и привязки к exchange."""
    exchange, dlx = await declare_exchanges(channel)
    dlq = await channel.declare_queue(spec.dlq, durable=True)
    await dlq.bind(dlx, routing_key=spec.dlq_key)
    queue = await channel.declare_queue(
        spec.name,
        durable=True,
        arguments={
            # Quorum-очередь считает доставки сообщения: заголовок
            # x-delivery-count, по нему consumer знает номер попытки.
            "x-queue-type": "quorum",
            "x-delivery-limit": DELIVERY_LIMIT,
            "x-dead-letter-exchange": DLX,
            "x-dead-letter-routing-key": spec.dlq_key,
        },
    )
    for key in spec.bindings:
        await queue.bind(exchange, routing_key=key)
    return queue


async def declare_all(channel: aio_pika.abc.AbstractChannel) -> None:
    for spec in ALL_QUEUES:
        await declare_queue(channel, spec)
