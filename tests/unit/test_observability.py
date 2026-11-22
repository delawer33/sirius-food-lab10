"""
Correlation ID проходит через HTTP, outbox и RabbitMQ; логи — JSON с этим ID.
"""
import asyncio
import io
import json
import logging
import sys
import uuid

import pytest
import structlog

from app.infrastructure.outbox import add_to_outbox
from app.domain.events import order_paid
from app.models import OutboxEvent
from messaging.consumer import Outcome, handle
from messaging.publisher import publish
from messaging.topology import KITCHEN
from observability import correlation
from observability.logging import setup_logging


@pytest.fixture
def log_lines():
    """JSON-строки логов, записанные во время теста."""
    stream = io.StringIO()
    # alembic.ini в тестах миграций выключает уже созданные logger'ы.
    for logger in logging.root.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):
            logger.disabled = False
    setup_logging("test", stream=stream)
    yield lambda: [json.loads(line) for line in stream.getvalue().splitlines()]
    setup_logging("test", stream=sys.stdout)
    structlog.contextvars.clear_contextvars()


@pytest.mark.parametrize("value", ["demo-42", "a1b2c3d4", "x" * 128])
def test_accept_keeps_valid_id(value):
    assert correlation.accept(value) == value


@pytest.mark.parametrize("value", [None, "", "has space", "x" * 129, "<script>", "id\nforged"])
def test_accept_replaces_invalid_id(value):
    uuid.UUID(correlation.accept(value))


def test_http_returns_client_id_and_logs_it(api, log_lines):
    response = api.client.get("/menu/items", headers={"X-Correlation-ID": "demo-42"})

    assert response.headers["X-Correlation-ID"] == "demo-42"
    request_logs = [line for line in log_lines() if line["message"] == "http_request"]
    assert request_logs[-1] | {"correlation_id": "demo-42", "path": "/menu/items", "status": 200} == request_logs[-1]


def test_http_generates_id_when_missing(api):
    response = api.client.get("/menu/items")
    uuid.UUID(response.headers["X-Correlation-ID"])


def test_outbox_stores_request_correlation_id(event_db):
    with event_db() as db, structlog.contextvars.bound_contextvars(correlation_id="demo-42"):
        add_to_outbox(db, [order_paid(1, 1, 250.0)])
        db.commit()
        assert db.query(OutboxEvent).one().correlation_id == "demo-42"


class FakeExchange:
    def __init__(self):
        self.sent = []

    async def publish(self, message, routing_key, mandatory):
        self.sent.append((routing_key, message))


def test_publish_puts_id_in_headers():
    exchange = FakeExchange()
    with structlog.contextvars.bound_contextvars(correlation_id="demo-42"):
        asyncio.run(publish(exchange, "order.paid", {"event_id": "e1", "order_id": 1}))
    assert exchange.sent[0][1].headers["X-Correlation-ID"] == "demo-42"


class FakeMessage:
    def __init__(self, payload, headers):
        self.body = json.dumps(payload).encode()
        self.headers = headers
        self.routing_key = "order.paid"
        self.result = None

    async def ack(self):
        self.result = "ack"

    async def reject(self, requeue):
        self.result = "reject"

    async def nack(self, requeue):
        self.result = "nack"


def test_consumer_logs_id_from_message_headers(log_lines):
    seen = []

    def handler(routing_key, payload):
        seen.append(correlation.current())
        return Outcome("принят", event="order_received")

    message = FakeMessage({"event_id": "e1", "order_id": 42}, {"X-Correlation-ID": b"demo-42"})
    asyncio.run(handle(message, KITCHEN, "kitchen", handler, FakeExchange(), retry_delay=0))

    assert message.result == "ack"
    # Обработчик работает в потоке, контекст доходит и туда.
    assert seen == ["demo-42"]
    received = next(line for line in log_lines() if line["message"] == "order_received")
    assert received | {"correlation_id": "demo-42", "order_id": 42, "queue": "kitchen_queue"} == received
    # После обработки ID не остаётся в контексте следующего сообщения.
    assert correlation.current() is None


def test_server_error_keeps_correlation_id(log_lines):
    from fastapi.testclient import TestClient

    from app.core.config import settings
    from app.main import create_app

    client = TestClient(create_app(settings.model_copy(update={"DEBUG": True, "CACHE_WARM_UP": False})))
    response = client.get("/debug/error", headers={"X-Correlation-ID": "demo-500"})

    assert response.status_code == 500
    assert response.headers["X-Correlation-ID"] == "demo-500"
    failed = next(line for line in log_lines() if line["message"] == "request_failed")
    assert failed["correlation_id"] == "demo-500" and "RuntimeError" in failed["exception"]
