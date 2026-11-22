"""
Заказ через HTTP до настоящего PostgreSQL: HTTP → сервис → репозиторий → БД.

    pytest tests/integration -v
"""
import json
import threading
import time

import pytest

from app.models import Order, OutboxEvent, User
from app.modules.orders.repository import SqlAlchemyOrderRepository
from app.modules.orders.service import OrderService
from app.domain.errors import BusinessRuleError
from tests.fakes import RecordingNotifier
from tests.integration.conftest import add_item, add_student, auth

pytestmark = pytest.mark.integration


def test_create_order_saves_to_db(client, pg, notifier):
    with pg() as db:
        user = add_student(db, balance=1000.0)
        item = add_item(db, "Сырники", 150.0)
        headers = auth(user)
        user_id, item_id = user.id, item.id

    response = client.post("/orders/create", json={"item_id": item_id, "quantity": 2}, headers=headers)

    assert response.status_code == 200
    order_id = response.json()["order_id"]
    with pg() as db:
        order = db.get(Order, order_id)
        assert (order.user_id, order.item_id, order.quantity, order.total_cost) == (user_id, item_id, 2, 300.0)
        assert order.status == "processing"
        assert db.get(User, user_id).balance == 700.0
        # Событие лежит в outbox той же транзакцией, что и заказ.
        event = db.query(OutboxEvent).one()
        payload = json.loads(event.payload)
        assert (event.routing_key, payload["event_type"]) == ("order.paid", "OrderPaid")
        assert (payload["order_id"], payload["amount"]) == (order_id, 300.0)
    assert notifier.calls == [(order_id, "anna@sirius.ru", None)]


def test_rejected_order_leaves_no_trace(client, pg, notifier):
    with pg() as db:
        user = add_student(db, balance=100.0)
        item = add_item(db, "Сырники", 150.0)
        headers, user_id, item_id = auth(user), user.id, item.id

    response = client.post("/orders/create", json={"item_id": item_id, "quantity": 1}, headers=headers)

    assert response.status_code == 400
    with pg() as db:
        assert db.query(Order).count() == 0
        assert db.query(OutboxEvent).count() == 0
        assert db.get(User, user_id).balance == 100.0
    assert notifier.calls == []


def test_each_test_starts_with_clean_db(pg):
    """Данные прошлых тестов сюда не попадают, счётчики id начинаются с единицы."""
    with pg() as db:
        assert db.query(User).count() == 0
        assert db.query(Order).count() == 0
        assert add_student(db).id == 1


def test_menu_item_from_postgres(client, pg):
    with pg() as db:
        item_id = add_item(db, "Борщ", 250.0).id

    found = client.get(f"/menu/items/{item_id}")
    missing = client.get("/menu/items/999")

    assert found.status_code == 200
    assert found.json()["name"] == "Борщ"
    assert missing.status_code == 404


class SlowRepository(SqlAlchemyOrderRepository):
    """Между проверкой баланса и записью проходит 0,3 с — окно для гонки."""

    def save_order(self, *args, **kwargs):
        time.sleep(0.3)
        return super().save_order(*args, **kwargs)


def test_parallel_orders_do_not_overspend(pg):
    """
    Денег на один заказ, два заказа одновременно. Должен пройти один.
    На SQLite в памяти (tests/conftest.py) эту гонку не увидеть: там одно
    соединение на все потоки.
    """
    with pg() as db:
        user_id = add_student(db, balance=300.0).id
        item_id = add_item(db, "Борщ", 250.0).id

    start = threading.Barrier(2)
    results: list[str] = []

    def order():
        with pg() as session:
            service = OrderService(SlowRepository(session), RecordingNotifier())
            start.wait()
            try:
                service.create_order(user_id, item_id, 1)
                results.append("ok")
            except BusinessRuleError:
                results.append("rejected")

    threads = [threading.Thread(target=order) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with pg() as db:
        orders = db.query(Order).count()
        balance = db.get(User, user_id).balance
    assert sorted(results) == ["ok", "rejected"]
    assert (orders, balance) == (1, 50.0)
