"""
Фоновые задачи без брокера: task.apply() выполняет задачу в этом же процессе
со всеми ретраями, хуками и идемпотентностью. Redis — fakeredis.
"""
import json
from datetime import timedelta

import pytest

from app.core import config
from app.models import Order, OrderStats, TaskLog, User
from app.tasks import base, maintenance
from app.tasks import orders as tasks
from app.tasks.base import DLQ_KEY


@pytest.fixture(autouse=True)
def task_env(redis, db_session, tmp_path, monkeypatch):
    for module in (tasks, base, maintenance):
        monkeypatch.setattr(module, "redis_client", redis)
    monkeypatch.setattr(config.settings, "RECEIPTS_DIR", str(tmp_path))
    monkeypatch.setattr(config.settings, "EMAIL_FAIL_EVERY", 5)


def logs(db_session):
    return [(row.task_name.rsplit(".", 1)[1], row.order_id, row.status)
            for row in db_session.query(TaskLog).order_by(TaskLog.id)]


def test_pdf_generated_once(redis, db_session, tmp_path):
    first = tasks.generate_order_pdf.apply(args=(7,))
    second = tasks.generate_order_pdf.apply(args=(7,))

    assert first.get().startswith("PDF generated for order 7")
    assert second.get() == "SKIP already done: pdf_generated:7"
    assert (tmp_path / "order_7.pdf.txt").exists()
    assert redis.get("pdf_generated:7") == "done"
    assert logs(db_session) == [("generate_order_pdf", 7, "success"),
                                ("generate_order_pdf", 7, "skipped")]


def test_email_and_sms_idempotent(redis):
    assert tasks.send_order_email.apply(args=(1, "a@sirius.ru")).get() == "Email sent to a@sirius.ru for order 1"
    assert tasks.send_order_email.apply(args=(1, "a@sirius.ru")).get().startswith("SKIP")
    assert tasks.send_order_sms.apply(args=(1, "+7999")).get() == "SMS sent to +7999 for order 1"
    assert tasks.send_order_sms.apply(args=(1, "+7999")).get().startswith("SKIP")


def test_concurrent_duplicate_is_skipped(redis):
    """Пока одна копия задачи работает, вторая не начинает ту же работу."""
    redis.set("email_sent:3", "running")

    assert tasks.send_order_email.apply(args=(3, "a@sirius.ru")).get() == "SKIP in progress: email_sent:3"


def test_failure_is_retried_then_succeeds(redis, db_session, monkeypatch):
    attempts = []

    def flaky(order_id, email):
        attempts.append(order_id)
        if len(attempts) < 3:
            raise tasks.ExternalServiceError("timeout")

    monkeypatch.setattr(tasks, "send_email", flaky)

    result = tasks.send_order_email.apply(args=(1, "a@sirius.ru"))

    assert result.get() == "Email sent to a@sirius.ru for order 1"
    assert len(attempts) == 3
    # Ключ идемпотентности снимается при ошибке, иначе ретрай пропустил бы работу.
    assert redis.get("email_sent:1") == "done"
    assert [s for _, _, s in logs(db_session)] == ["retry", "retry", "success"]
    assert redis.llen(DLQ_KEY) == 0


def test_exhausted_retries_go_to_dlq(redis, db_session):
    """Каждый 5-й заказ: почта «лежит», 1 попытка + 3 ретрая, потом DLQ."""
    result = tasks.send_order_email.apply(args=(5, "a@sirius.ru"))

    assert result.failed()
    assert [s for _, _, s in logs(db_session)] == ["retry", "retry", "retry", "failed"]
    [record] = [json.loads(r) for r in redis.lrange(DLQ_KEY, 0, -1)]
    assert record["task"] == "app.tasks.orders.send_order_email"
    assert record["args"] == [5, "a@sirius.ru"]
    assert record["retries"] == 3
    assert "Email service unavailable" in record["error"]
    assert redis.exists("email_sent:5") == 0  # можно перезапустить из DLQ


def test_retry_policy_is_exponential():
    task = tasks.send_order_email
    assert (task.max_retries, task.retry_backoff, task.retry_jitter) == (3, 1, True)
    assert task.autoretry_for == (Exception,)


def test_update_order_stats(db_session, redis):
    db_session.add(User(id=1, email="a@sirius.ru", password_hash="!", role_id=1))
    now = maintenance._now()
    db_session.add_all([
        Order(user_id=1, item_id=None, quantity=1, status="processing", total_cost=100, created_at=now),
        Order(user_id=1, item_id=None, quantity=1, status="delivered", total_cost=250, created_at=now),
        Order(user_id=1, item_id=None, quantity=1, status="cancelled", total_cost=999, created_at=now),
        Order(user_id=1, item_id=None, quantity=1, status="delivered", total_cost=500,
              created_at=now - timedelta(days=1)),
    ])
    db_session.commit()

    stats = maintenance.update_order_stats.apply().get()

    assert (stats["orders_count"], stats["revenue"]) == (2, 350.0)
    assert json.loads(redis.get(f"stats:orders:{stats['day']}")) == stats
    db_session.expire_all()
    row = db_session.query(OrderStats).one()
    assert (row.orders_count, row.revenue) == (2, 350.0)

    maintenance.update_order_stats.apply().get()  # повтор обновляет ту же строку
    assert db_session.query(OrderStats).count() == 1


def test_cleanup_task_logs(db_session):
    now = maintenance._now()
    db_session.add_all([
        TaskLog(task_id="old", task_name="t", status="success", created_at=now - timedelta(days=31)),
        TaskLog(task_id="new", task_name="t", status="success", created_at=now - timedelta(days=29)),
    ])
    db_session.commit()

    assert maintenance.cleanup_task_logs.apply().get() == 1
    assert [r.task_id for r in db_session.query(TaskLog)] == ["new"]


def test_beat_schedule():
    from app.core.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    assert schedule["update-order-stats-every-minute"]["schedule"] == 60.0
    assert schedule["cleanup-task-logs-daily"]["task"] == "app.tasks.maintenance.cleanup_task_logs"
