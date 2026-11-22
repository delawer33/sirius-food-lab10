"""
Pact, сторона provider'а: монолит проверяет, что его события подходят кухне.

Сообщения строит настоящий OrderService — тот же код, что кладёт событие в
outbox при заказе и отмене. Pact сверяет их с pacts/kitchen-monolith.json:
переименуй order_id в событии, и тест упадёт.
"""
import json
from pathlib import Path

from pact import Verifier

from app.domain.entities import MenuItem, User
from app.infrastructure.memory import InMemoryStorage
from app.modules.orders.repository import InMemoryOrderRepository
from app.modules.orders.service import OrderService
from tests.fakes import RecordingNotifier

PACT_FILE = Path(__file__).resolve().parents[2] / "pacts" / "kitchen-monolith.json"


def _service() -> tuple[OrderService, InMemoryStorage]:
    storage = InMemoryStorage()
    storage.users[1] = User(1, "anna@sirius.ru", None, 1000.0, False, "student")
    storage.menu_items[1] = MenuItem(1, "Борщ", 250.0, True)
    return OrderService(InMemoryOrderRepository(storage), RecordingNotifier()), storage


def _message(event) -> dict:
    return {
        "contents": json.dumps(event.payload).encode(),
        "metadata": {"routing_key": event.routing_key},
        "content_type": "application/json",
    }


def order_paid():
    service, storage = _service()
    service.create_order(user_id=1, item_id=1, quantity=1)
    return _message(storage.outbox[-1])


def order_cancelled():
    service, storage = _service()
    order_id = service.create_order(user_id=1, item_id=1, quantity=1)
    service.cancel_order(order_id, storage.users[1])
    return _message(storage.outbox[-1])


def test_monolith_events_match_kitchen_contract():
    assert PACT_FILE.exists(), "сначала test_kitchen_consumer.py: он пишет контракт"
    (Verifier("monolith")
        .message_handler({"OrderPaid": order_paid, "OrderCancelled": order_cancelled})
        .add_source(PACT_FILE)
        .verify())
