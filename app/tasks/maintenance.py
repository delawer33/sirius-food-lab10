"""
Периодические задачи (Celery Beat). Расписание — в app/core/celery_app.py.
"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from app.core.celery_app import celery_app
from app.core.redis import redis_client
from app.database import SessionLocal
from app.domain.entities import ORDER_CANCELLED
from app.models import Order, OrderStats, TaskLog

TASK_LOG_RETENTION_DAYS = 30


def _now() -> datetime:
    # В БД время хранится в UTC без часового пояса.
    return datetime.now(timezone.utc).replace(tzinfo=None)


@celery_app.task
def update_order_stats() -> dict:
    """
    Раз в минуту: число заказов и выручка за сегодня (UTC). Пишется в таблицу
    order_stats и в Redis (stats:orders:<дата>) — оттуда её быстро читать.
    """
    now = _now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    with SessionLocal() as db:
        count, revenue = (
            db.query(func.count(Order.id), func.coalesce(func.sum(Order.total_cost), 0.0))
            .filter(Order.created_at >= start, Order.status != ORDER_CANCELLED)
            .one()
        )
        row = db.get(OrderStats, start.date())
        if row is None:
            row = OrderStats(day=start.date())
            db.add(row)
        row.orders_count, row.revenue, row.updated_at = count, float(revenue), now
        db.commit()
    stats = {"day": start.date().isoformat(), "orders_count": count, "revenue": float(revenue)}
    redis_client.set(f"stats:orders:{stats['day']}", json.dumps(stats), ex=2 * 86400)
    return stats


@celery_app.task
def cleanup_task_logs() -> int:
    """Раз в сутки: удалить записи журнала задач старше 30 дней."""
    border = _now() - timedelta(days=TASK_LOG_RETENTION_DAYS)
    with SessionLocal() as db:
        deleted = db.query(TaskLog).filter(TaskLog.created_at < border).delete()
        db.commit()
    return deleted
