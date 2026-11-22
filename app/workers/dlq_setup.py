"""
Объявляет exchange, DLX, все очереди и их DLQ. Запустить один раз до
consumer'ов (они объявляют то же самое при старте, так что это не обязательно).

    python -m app.workers.dlq_setup
"""
import asyncio

import aio_pika

from app.core.config import settings
from messaging.topology import ALL_QUEUES, DLX, EXCHANGE, declare_all


async def connect_when_ready(attempts: int = 30) -> aio_pika.abc.AbstractConnection:
    """Сразу после docker compose up RabbitMQ ещё стартует и рвёт соединения — ждём."""
    for attempt in range(1, attempts + 1):
        try:
            return await aio_pika.connect(settings.RABBITMQ_URL)
        except (aio_pika.exceptions.AMQPConnectionError, OSError):
            if attempt == attempts:
                raise
            print(f"RabbitMQ ещё не готов, жду... ({attempt}/{attempts})")
            await asyncio.sleep(1)


async def setup() -> None:
    connection = await connect_when_ready()
    async with connection:
        await declare_all(await connection.channel())
    print(f"exchange {EXCHANGE} (topic), DLX {DLX} (direct)")
    for spec in ALL_QUEUES:
        print(f"  {spec.name:18} ← {', '.join(spec.bindings):28} отказ → {DLX} [{spec.dlq_key}] → {spec.dlq}")
    print("DLQ настроена.")


if __name__ == "__main__":
    asyncio.run(setup())
