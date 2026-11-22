"""
Какие события пишет сервис заказов и что они попадают в outbox той же транзакцией.
"""
import json

import pytest

from app.domain.entities import Delivery, MenuItem, Order, User
from app.domain.errors import AlreadyRefundedError
from app.models import Order as OrderModel
from app.models import OutboxEvent, Refund
from app.models import User as UserModel
from app.modules.delivery.repository import InMemoryDeliveryGateway, InMemoryDeliveryRepository
from app.modules.delivery.service import DeliveryService
from app.modules.orders.repository import InMemoryOrderRepository, SqlAlchemyOrderRepository
from app.modules.orders.service import OrderService
from tests.fakes import RecordingNotifier

ANNA = User(1, "anna@sirius.ru", None, 1000.0, False, "student")
ADMIN = User(9, "admin@sirius.ru", None, 0.0, False, "admin")


@pytest.fixture
def service(storage):
    storage.users[1] = User(1, "anna@sirius.ru", None, 1000.0, False)
    storage.menu_items[1] = MenuItem(1, "Борщ", 250.0, True)
    return OrderService(InMemoryOrderRepository(storage), RecordingNotifier())


def test_create_order_emits_order_paid(service, storage):
    order_id = service.create_order(1, 1, 2)

    [event] = storage.outbox
    assert event.routing_key == "order.paid"
    assert event.payload | {"event_id": "-", "occurred_at": "-"} == {
        "event_id": "-", "occurred_at": "-", "event_type": "OrderPaid",
        "order_id": order_id, "customer_id": 1, "amount": 500.0,
    }


def test_each_event_has_own_id(service, storage):
    service.create_order(1, 1, 1)
    service.create_order(1, 1, 1)
    assert len({e.event_id for e in storage.outbox}) == 2


def test_client_cancel_emits_order_cancelled(service, storage):
    order_id = service.create_order(1, 1, 1)
    service.cancel_order(order_id, ANNA)

    event = storage.outbox[-1]
    assert (event.routing_key, event.payload["reason"], event.payload["refund"]) == ("order.cancelled", "client", 250.0)
    assert storage.refunds == {order_id: 250.0}


def test_compensation_cancels_and_refunds_once(service, storage):
    order_id = service.create_order(1, 1, 1)
    assert storage.users[1].balance == 750.0

    first = service.compensate_failed_delivery(order_id)
    second = service.compensate_failed_delivery(order_id)

    assert first.status == "cancelled" and second is None
    assert storage.users[1].balance == 1000.0
    assert [e.routing_key for e in storage.outbox] == ["order.paid", "order.cancelled"]
    assert storage.outbox[-1].payload["reason"] == "delivery_failed"


def test_compensation_of_ready_order(service):
    order_id = service.create_order(1, 1, 1)
    service.mark_ready(order_id)
    assert service.compensate_failed_delivery(order_id).status == "cancelled"


def test_no_compensation_for_delivered_order(service, storage):
    order_id = service.create_order(1, 1, 1)
    storage.orders[order_id].status = "delivered"
    assert service.compensate_failed_delivery(order_id) is None
    assert storage.users[1].balance == 750.0


def test_complete_delivery_emits_order_delivered(storage):
    storage.orders[1] = Order(1, 1, 1, 1, "delivering", 250.0)
    storage.deliveries[1] = Delivery(1, 1, 4, "in_progress")
    service = DeliveryService(InMemoryDeliveryRepository(storage), InMemoryDeliveryGateway(storage))

    service.complete_delivery(1, ADMIN)

    [event] = storage.outbox
    assert event.routing_key == "order.delivered"
    assert (event.payload["order_id"], event.payload["delivery_id"], event.payload["courier_id"]) == (1, 1, 4)


# --- SQL: событие в outbox той же транзакцией ---

def test_sql_order_and_event_saved_together(event_db):
    with event_db() as db:
        order_id = OrderService(SqlAlchemyOrderRepository(db), RecordingNotifier()).create_order(1, 1, 1)
    with event_db() as db:
        [row] = db.query(OutboxEvent).all()
        assert row.routing_key == "order.paid" and row.published_at is None
        assert json.loads(row.payload)["order_id"] == order_id


def test_sql_no_order_without_event(event_db):
    """Сбой при записи события откатывает и заказ, и списание денег."""
    def broken(order_id):
        raise RuntimeError("outbox сломан")

    with event_db() as db:
        with pytest.raises(RuntimeError):
            SqlAlchemyOrderRepository(db).save_order(1, 1, 1, 250.0, 750.0, make_events=broken)
        db.rollback()
    with event_db() as db:
        assert db.query(OrderModel).count() == 0
        assert db.query(OutboxEvent).count() == 0
        assert db.get(UserModel, 1).balance == 1000.0


def test_sql_second_refund_rejected(event_db):
    with event_db() as db:
        service = OrderService(SqlAlchemyOrderRepository(db), RecordingNotifier())
        order_id = service.create_order(1, 1, 1)
        service.compensate_failed_delivery(order_id)
        with pytest.raises(AlreadyRefundedError):
            SqlAlchemyOrderRepository(db).cancel_order(order_id, "cancelled", 2000.0, reason="again")
    with event_db() as db:
        assert db.query(Refund).count() == 1
        assert db.get(UserModel, 1).balance == 1000.0
