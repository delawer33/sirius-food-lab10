"""
Доменные события заказа. Сервис решает, какое событие произошло, репозиторий
записывает его в outbox в одной транзакции с изменением данных.

event_id — ключ идемпотентности: consumer, увидев его второй раз, пропускает сообщение.
"""
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

ORDER_PAID = "order.paid"
ORDER_CANCELLED = "order.cancelled"
ORDER_DELIVERED = "order.delivered"


@dataclass(frozen=True)
class DomainEvent:
    routing_key: str
    payload: dict

    @property
    def event_id(self) -> str:
        return self.payload["event_id"]


def _event(routing_key: str, event_type: str, **data) -> DomainEvent:
    return DomainEvent(routing_key, {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "occurred_at": datetime.now(UTC).isoformat(timespec="seconds"),
        **data,
    })


def order_paid(order_id: int, customer_id: int, amount: float) -> DomainEvent:
    return _event(ORDER_PAID, "OrderPaid", order_id=order_id, customer_id=customer_id, amount=amount)


def order_cancelled(order_id: int, customer_id: int, refund: float, reason: str) -> DomainEvent:
    return _event(ORDER_CANCELLED, "OrderCancelled", order_id=order_id, customer_id=customer_id,
                  refund=refund, reason=reason)


def order_delivered(order_id: int, delivery_id: int, courier_id: int) -> DomainEvent:
    return _event(ORDER_DELIVERED, "OrderDelivered", order_id=order_id, delivery_id=delivery_id,
                  courier_id=courier_id)
