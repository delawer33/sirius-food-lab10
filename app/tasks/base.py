"""
Базовый класс задач: журнал выполнения и Dead Letter Queue.

Celery вызывает хуки сам: on_retry — перед каждым повтором, on_failure —
когда ретраи кончились и задача окончательно упала, on_success — при успехе.
"""
import json
import logging
from datetime import datetime, timezone

from celery import Task
from redis.exceptions import RedisError

from app.core.redis import redis_client
from app.database import SessionLocal
from app.models import TaskLog

logger = logging.getLogger(__name__)

DLQ_KEY = "dlq"


def write_log(task_id: str, task_name: str, order_id: int | None, status: str, detail: str = "") -> None:
    try:
        with SessionLocal() as db:
            db.add(TaskLog(task_id=task_id, task_name=task_name, order_id=order_id,
                           status=status, detail=detail[:500]))
            db.commit()
    except Exception:
        # Журнал вспомогательный: из-за него задача падать не должна.
        logger.exception("Не удалось записать журнал задачи %s", task_id)


class LoggedTask(Task):
    abstract = True

    def on_success(self, retval, task_id, args, kwargs):
        status = "skipped" if isinstance(retval, str) and retval.startswith("SKIP") else "success"
        write_log(task_id, self.name, _order_id(args, kwargs), status, str(retval))

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        write_log(task_id, self.name, _order_id(args, kwargs), "retry", repr(exc))

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Ретраи исчерпаны: задача уходит в DLQ, чтобы её не потерять."""
        record = {
            "task_id": task_id,
            "task": self.name,
            "args": list(args),
            "kwargs": kwargs,
            "error": repr(exc),
            "retries": self.request.retries,
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            redis_client.rpush(DLQ_KEY, json.dumps(record, ensure_ascii=False))
        except RedisError:
            logger.exception("DLQ недоступна, задача %s потеряна: %s", task_id, record)
        logger.error("Задача %s ушла в DLQ после %s попыток: %r", task_id, self.request.retries + 1, exc)
        write_log(task_id, self.name, _order_id(args, kwargs), "failed", repr(exc))


def _order_id(args, kwargs) -> int | None:
    value = kwargs.get("order_id", args[0] if args else None)
    return value if isinstance(value, int) else None
