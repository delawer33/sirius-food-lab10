"""
Доменные события: форма payload, которую читают consumer'ы.
Добавлено по итогам mutmut (ЛР № 10): ключи и типы событий не проверял никто.
"""
from datetime import datetime

from app.domain import events


def test_order_paid_payload():
    event = events.order_paid(order_id=5, customer_id=1, amount=300.0)

    assert event.routing_key == "order.paid"
    assert {k: v for k, v in event.payload.items() if k not in ("event_id", "occurred_at")} == {
        "event_type": "OrderPaid", "order_id": 5, "customer_id": 1, "amount": 300.0,
    }


def test_order_cancelled_payload():
    event = events.order_cancelled(order_id=5, customer_id=1, refund=300.0, reason="client")

    assert event.routing_key == "order.cancelled"
    assert {k: v for k, v in event.payload.items() if k not in ("event_id", "occurred_at")} == {
        "event_type": "OrderCancelled", "order_id": 5, "customer_id": 1, "refund": 300.0, "reason": "client",
    }


def test_order_delivered_payload():
    event = events.order_delivered(order_id=5, delivery_id=2, courier_id=3)

    assert event.routing_key == "order.delivered"
    assert {k: v for k, v in event.payload.items() if k not in ("event_id", "occurred_at")} == {
        "event_type": "OrderDelivered", "order_id": 5, "delivery_id": 2, "courier_id": 3,
    }


def test_each_event_has_unique_id_and_utc_time():
    first, second = events.order_paid(1, 1, 1.0), events.order_paid(1, 1, 1.0)

    assert first.event_id != second.event_id
    assert first.event_id == first.payload["event_id"]
    assert datetime.fromisoformat(first.payload["occurred_at"]).utcoffset().total_seconds() == 0
