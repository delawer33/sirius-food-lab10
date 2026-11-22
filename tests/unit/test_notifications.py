"""
Реализации OrderNotifier и разбор DLQ.
"""
import json

import pytest
from kombu.exceptions import OperationalError

from app.core import config
from app.infrastructure import notifications
from app.infrastructure.notifications import CeleryOrderNotifier, SyncOrderNotifier
from app.tasks import orders as tasks
from scripts import dlq


@pytest.fixture
def queued(monkeypatch):
    """Перехватывает постановку задач в очередь."""
    sent = []
    for task in (tasks.generate_order_pdf, tasks.send_order_email, tasks.send_order_sms):
        monkeypatch.setattr(task, "apply_async",
                            lambda args, name=task.name, **kw: sent.append((name.rsplit(".", 1)[1], tuple(args))))
    return sent


def test_celery_notifier_queues_three_tasks(queued):
    CeleryOrderNotifier().order_created(7, "a@sirius.ru", "+7999")

    assert queued == [("generate_order_pdf", (7,)), ("send_order_email", (7, "a@sirius.ru")),
                      ("send_order_sms", (7, "+7999"))]


def test_no_sms_without_phone(queued):
    CeleryOrderNotifier().order_created(7, "a@sirius.ru", None)

    assert [name for name, _ in queued] == ["generate_order_pdf", "send_order_email"]


def test_broker_down_does_not_break_order(monkeypatch, caplog):
    # alembic fileConfig в тестах миграций отключает уже созданные логгеры.
    monkeypatch.setattr(notifications.logger, "disabled", False)

    def down(*args, **kwargs):
        raise OperationalError("broker is down")

    for task in (tasks.generate_order_pdf, tasks.send_order_email, tasks.send_order_sms):
        monkeypatch.setattr(task, "apply_async", down)

    CeleryOrderNotifier().order_created(7, "a@sirius.ru", "+7999")  # не бросает

    assert caplog.text.count("Не удалось поставить") == 3


def test_sync_notifier_does_work_in_request(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "RECEIPTS_DIR", str(tmp_path))
    monkeypatch.setattr(config.settings, "EMAIL_FAIL_EVERY", 0)

    SyncOrderNotifier().order_created(7, "a@sirius.ru", "+7999")

    assert (tmp_path / "order_7.pdf.txt").exists()


class FakeApp:
    def __init__(self):
        self.sent = []

    def send_task(self, name, args, kwargs):
        self.sent.append((name, args))


def test_dlq_retry(redis):
    for order_id in (5, 10):
        redis.rpush("dlq", json.dumps({"task": "app.tasks.orders.send_order_email",
                                       "args": [order_id, "a@sirius.ru"], "kwargs": {}}))
    app = FakeApp()

    assert [r["args"][0] for r in dlq.list_dead(redis)] == [5, 10]
    assert dlq.retry(1, redis, app) == 1
    assert app.sent == [("app.tasks.orders.send_order_email", [10, "a@sirius.ru"])]
    assert [r["args"][0] for r in dlq.list_dead(redis)] == [5]
