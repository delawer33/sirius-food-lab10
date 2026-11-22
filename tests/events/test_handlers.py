"""
Обработчики consumer'ов без брокера: что они делают с БД при первой
и повторной доставке события.
"""
import uuid

import pytest

from app.models import KitchenOrder, OutboxEvent, ProcessedEvent, Refund
from app.models import Order as OrderModel
from app.models import User as UserModel
from app.workers.kitchen_consumer import KitchenHandler
from app.workers.saga_consumer import SagaHandler
from delivery_service.storage import CourierShiftRow, DeliveryRequestRow, DeliveryRow
from delivery_service.worker import DeliveryPlanner
from messaging.consumer import BadMessage, parse
from tests.events.helpers import add_order


def paid(order_id, event_id=None):
    return {"event_id": event_id or str(uuid.uuid4()), "order_id": order_id, "customer_id": 1, "amount": 250.0}


# --- разбор сообщения ---

@pytest.mark.parametrize("body", [b"not-json", b"[1, 2]", b'{"order_id": 1}', b'{"event_id": "x", "order_id": "1"}'])
def test_bad_messages(body):
    with pytest.raises(BadMessage):
        parse(body)


def test_good_message():
    assert parse(b'{"event_id": "e1", "order_id": 42}')["order_id"] == 42


# --- кухня ---

def test_kitchen_accepts_order(event_db):
    outcome = KitchenHandler(event_db)("order.paid", paid(42))
    assert outcome.log.startswith("Принят заказ 42")
    with event_db() as db:
        assert [(r.order_id, r.status) for r in db.query(KitchenOrder)] == [(42, "pending")]


def test_kitchen_skips_duplicate(event_db):
    handler, event = KitchenHandler(event_db), paid(42)
    handler("order.paid", event)
    outcome = handler("order.paid", event)

    assert outcome.log.startswith("Повтор")
    with event_db() as db:
        assert db.query(KitchenOrder).count() == 1
        assert db.query(ProcessedEvent).count() == 1


def test_kitchen_cancels_order(event_db):
    handler = KitchenHandler(event_db)
    handler("order.paid", paid(42))
    handler("order.cancelled", {"event_id": "c1", "order_id": 42, "reason": "delivery_failed"})
    with event_db() as db:
        assert db.query(KitchenOrder).one().status == "cancelled"


# --- доставка ---

def shifts(session_factory, *couriers, busy=()):
    with session_factory() as db:
        db.add_all(CourierShiftRow(courier_id=c, on_shift=on) for c, on in couriers)
        db.add_all(DeliveryRow(order_id=100 + c, courier_id=c, status="in_progress") for c in busy)
        db.commit()


def test_delivery_with_free_courier(event_db):
    shifts(event_db, (4, True))
    outcome = DeliveryPlanner(event_db)("order.paid", paid(42))

    assert outcome.publish == []
    with event_db() as db:
        request = db.get(DeliveryRequestRow, 42)
        assert (request.status, request.free_couriers) == ("waiting_courier", 1)


@pytest.mark.parametrize("couriers,busy", [((), ()), (((4, False),), ()), (((4, True),), (4,))])
def test_no_free_courier_fails_delivery(event_db, couriers, busy):
    """Нет курьеров, все не на смене или все заняты — delivery.failed."""
    shifts(event_db, *couriers, busy=busy)
    outcome = DeliveryPlanner(event_db)("order.paid", paid(42))

    [(key, event)] = outcome.publish
    assert (key, event["order_id"]) == ("delivery.failed", 42)
    with event_db() as db:
        assert db.get(DeliveryRequestRow, 42).status == "no_courier"


def test_failed_delivery_replayed_with_same_event_id(event_db):
    """Повтор order.paid после сбоя публикации: delivery.failed с тем же event_id."""
    planner, event = DeliveryPlanner(event_db), paid(42)
    first = planner("order.paid", event)
    second = planner("order.paid", event)
    assert first.publish[0][1]["event_id"] == second.publish[0][1]["event_id"]


def test_delivery_duplicate_with_courier_publishes_nothing(event_db):
    shifts(event_db, (4, True))
    planner, event = DeliveryPlanner(event_db), paid(42)
    planner("order.paid", event)
    assert planner("order.paid", event).publish == []


# --- сага ---

def test_saga_compensates_once(event_db):
    order_id = add_order(event_db)
    with event_db() as db:
        db.get(UserModel, 1).balance = 750.0
        db.commit()
    failed = {"event_id": "f1", "order_id": order_id, "reason": "Нет свободных курьеров"}

    first = SagaHandler(event_db)("delivery.failed", failed)
    second = SagaHandler(event_db)("delivery.failed", failed)

    assert first.log.startswith(f"Компенсация заказа {order_id}")
    assert second.log.startswith("Повтор")
    with event_db() as db:
        assert db.get(OrderModel, order_id).status == "cancelled"
        assert db.get(UserModel, 1).balance == 1000.0
        assert db.query(Refund).count() == 1
        assert [r.routing_key for r in db.query(OutboxEvent)] == ["order.cancelled"]
