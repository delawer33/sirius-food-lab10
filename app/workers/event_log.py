"""
Журнал всех событий: очередь привязана к ключу # и получает копию каждого
события. Показывает, что и в каком порядке летит через брокер.

    python -m app.workers.event_log
"""
import asyncio
import json

import observability
from app.core.config import settings
from messaging.consumer import Outcome, consume
from messaging.topology import EVENT_LOG


def log_event(routing_key: str, payload: dict) -> Outcome:
    return Outcome(f"{routing_key} {json.dumps(payload, ensure_ascii=False)}", event="event_logged")


async def main() -> None:
    observability.setup("event-log")
    await consume(settings.RABBITMQ_URL, EVENT_LOG, "Events", log_event)


if __name__ == "__main__":
    asyncio.run(main())
