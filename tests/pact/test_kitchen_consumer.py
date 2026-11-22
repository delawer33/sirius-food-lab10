"""
Pact, сторона consumer'а: кухня описывает, какие события ей нужны от монолита.

Тест прогоняет пример сообщения из контракта через тот же разбор и обработчик,
что работают в kitchen_consumer, и пишет контракт в pacts/kitchen-monolith.json.
Монолит проверяет себя по этому файлу в test_monolith_provider.py.

    pytest tests/pact -v
"""
import json
from pathlib import Path

import pytest
from pact import Pact, match

from app.models import KitchenOrder
from app.workers.kitchen_consumer import KitchenHandler
from messaging.consumer import parse

PACT_DIR = Path(__file__).resolve().parents[2] / "pacts"

# Кухня читает только эти поля (app/workers/kitchen_consumer.py, messaging/consumer.py).
# Остальное в событии ей не нужно, поэтому в контракт не входит: монолит
# может менять amount или customer_id, не ломая кухню.
ORDER_PAID = {
    "event_id": match.uuid("6f1c2a52-6d2e-4d8f-9a55-0c3b5e8a1d10"),
    "event_type": "OrderPaid",
    "order_id": match.int(42),
}
ORDER_CANCELLED = {
    "event_id": match.uuid("0b7e9d41-1f0a-4c8e-b8e3-2d4f6a9c7e21"),
    "event_type": "OrderCancelled",
    "order_id": match.int(42),
    "reason": match.str("client"),
}


@pytest.fixture(scope="module")
def pact():
    pact = Pact("kitchen", "monolith").with_specification("V4")
    yield pact
    pact.write_file(PACT_DIR, overwrite=True)


@pytest.fixture
def kitchen(event_db):
    """Обработчик кухни на чистой SQLite. Возвращает handler в формате Pact."""
    handle = KitchenHandler(event_db)

    def handler(body, metadata):
        handle(metadata["routing_key"], parse(body if isinstance(body, bytes) else body.encode()))

    return handler


def kitchen_orders(event_db):
    with event_db() as db:
        return [(row.order_id, row.status) for row in db.query(KitchenOrder)]


def test_order_paid_puts_order_into_kitchen(pact, kitchen, event_db):
    (pact.upon_receiving("OrderPaid", "Async")
        .with_body(ORDER_PAID, content_type="application/json")
        .with_metadata({"routing_key": "order.paid"}))

    pact.verify(kitchen, "Async")

    assert kitchen_orders(event_db) == [(42, "pending")]


def test_order_cancelled_removes_order_from_kitchen(pact, kitchen, event_db):
    (pact.upon_receiving("OrderCancelled", "Async")
        .with_body(ORDER_CANCELLED, content_type="application/json")
        .with_metadata({"routing_key": "order.cancelled"}))

    # verify прогоняет все сообщения контракта по порядку: OrderPaid, затем OrderCancelled.
    pact.verify(kitchen, "Async")

    assert kitchen_orders(event_db) == [(42, "cancelled")]
