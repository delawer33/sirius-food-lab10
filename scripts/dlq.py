"""
Разбор Dead Letter Queue — задач, которые упали после всех ретраев.

    python -m scripts.dlq list          # показать
    python -m scripts.dlq retry         # поставить все заново в очередь
    python -m scripts.dlq retry 0       # только первую

Снимать ключ идемпотентности перед перезапуском не нужно: упавшая задача
сняла его сама.
"""
import json
import sys

from app.core.celery_app import celery_app
from app.core.redis import redis_client
from app.tasks.base import DLQ_KEY


def list_dead(redis=redis_client) -> list[dict]:
    return [json.loads(raw) for raw in redis.lrange(DLQ_KEY, 0, -1)]


def retry(index: int | None = None, redis=redis_client, app=celery_app) -> int:
    """Ставит задачи из DLQ обратно в очередь и убирает их из DLQ."""
    raws = redis.lrange(DLQ_KEY, 0, -1)
    chosen = raws if index is None else [raws[index]]
    for raw in chosen:
        record = json.loads(raw)
        app.send_task(record["task"], args=record["args"], kwargs=record["kwargs"])
        redis.lrem(DLQ_KEY, 1, raw)
    return len(chosen)


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "list"
    if command == "list":
        dead = list_dead()
        for i, record in enumerate(dead):
            print(f"[{i}] {record['failed_at']} {record['task']}{tuple(record['args'])} -> {record['error']}")
        print(f"Всего в DLQ: {len(dead)}")
    elif command == "retry":
        index = int(sys.argv[2]) if len(sys.argv) > 2 else None
        print(f"Поставлено заново: {retry(index)}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
