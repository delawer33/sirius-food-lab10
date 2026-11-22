"""
Интеграционные тесты на настоящем RabbitMQ (testcontainers поднимает его в Docker).

Без Docker тесты пропускаются. Запуск только их:

    pytest tests/integration -v

Consumer'ы, релей outbox и сага работают как в продакшене, отличие одно:
БД — SQLite в памяти вместо PostgreSQL.
"""
import asyncio
import json
import os
import uuid

import aio_pika
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import MenuItem, Role, seed_roles
from delivery_service.storage import Base as DeliveryBase

from app.models import KitchenOrder, OutboxEvent, Refund
from app.models import Order as OrderModel
from app.models import User as UserModel
from app.modules.orders.repository import SqlAlchemyOrderRepository
from app.modules.orders.service import OrderService
from app.workers.kitchen_consumer import KitchenHandler
from app.workers.outbox_relay import relay_forever
from app.workers.saga_consumer import SagaHandler
from delivery_service.storage import CourierShiftRow, DeliveryRequestRow
from delivery_service.worker import DeliveryPlanner
from messaging.consumer import consume
from messaging.topology import ALL_QUEUES, DELIVERY, EXCHANGE, KITCHEN, SAGA, QueueSpec, declare_all
from tests.fakes import RecordingNotifier

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def rabbit_url():
    # Ryuk — контейнер-уборщик testcontainers. Контейнер и так останавливается
    # в конце сессии, а лишний образ из Docker Hub не нужен.
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
    try:
        from testcontainers.rabbitmq import RabbitMqContainer
        container = RabbitMqContainer("rabbitmq:3.13-management", username="sirius", password="sirius")
        container.start()
    except Exception as error:  # нет Docker или образа
        pytest.skip(f"RabbitMQ в Docker недоступен: {error}")
    params = container.get_connection_params()
    yield f"amqp://sirius:sirius@{params.host}:{params.port}/"
    container.stop()


@pytest.fixture
def event_db(tmp_path):
    """
    Файловая SQLite: у каждого потока своё соединение, как с PostgreSQL.
    SQLite в памяти из tests/conftest.py — одно соединение на всех, а здесь
    consumer'ы и релей работают одновременно.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'events.db'}",
                           connect_args={"check_same_thread": False, "timeout": 10})
    Base.metadata.create_all(engine)
    DeliveryBase.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)
    with session_factory() as db:
        seed_roles(db)
        student = db.query(Role).filter_by(name="student").one()
        db.add(UserModel(id=1, email="anna@sirius.ru", balance=1000.0, password_hash="h", role_id=student.id))
        db.add(MenuItem(id=1, name="Борщ", price=250.0))
        db.commit()
    yield session_factory
    engine.dispose()


async def reset_broker(url):
    """Пустые очереди перед каждым тестом."""
    connection = await aio_pika.connect(url)
    async with connection:
        channel = await connection.channel()
        await declare_all(channel)
        for spec in ALL_QUEUES:
            for name in (spec.name, spec.dlq):
                await (await channel.get_queue(name)).purge()


async def publish_raw(url, routing_key, body: bytes):
    connection = await aio_pika.connect(url)
    async with connection:
        channel = await connection.channel()
        exchange = await channel.get_exchange(EXCHANGE)
        await exchange.publish(aio_pika.Message(body=body), routing_key=routing_key)


async def queue_size(url, name) -> int:
    connection = await aio_pika.connect(url)
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(name, passive=True)
        return queue.declaration_result.message_count


async def wait_for(check, timeout=10.0):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if await check():
            return
        await asyncio.sleep(0.1)
    raise AssertionError("не дождались")


class Running:
    """Запускает корутины consumer'ов фоном и останавливает их в конце теста."""

    def __init__(self, *coroutines):
        self.coroutines = coroutines

    async def __aenter__(self):
        self.tasks = [asyncio.create_task(c) for c in self.coroutines]
        await asyncio.sleep(0.5)  # consumer'ы подписались
        return self

    async def __aexit__(self, *exc):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


def run(coroutine):
    asyncio.run(coroutine)


def kitchen_rows(session_factory):
    with session_factory() as db:
        return [(r.order_id, r.status) for r in db.query(KitchenOrder).order_by(KitchenOrder.order_id)]


def paid_body(order_id, event_id=None) -> bytes:
    return json.dumps({"event_id": event_id or str(uuid.uuid4()), "order_id": order_id}).encode()


def test_kitchen_consumes_order_paid(rabbit_url, event_db):
    async def scenario():
        await reset_broker(rabbit_url)
        async with Running(consume(rabbit_url, KITCHEN, "Kitchen", KitchenHandler(event_db))):
            await publish_raw(rabbit_url, "order.paid", paid_body(42))

            async def done():
                return kitchen_rows(event_db) == [(42, "pending")]
            await wait_for(done)
    run(scenario())


def test_kitchen_and_delivery_get_same_event_independently(rabbit_url, event_db):
    with event_db() as db:
        db.add(CourierShiftRow(courier_id=4, on_shift=True))
        db.commit()

    async def scenario():
        await reset_broker(rabbit_url)
        async with Running(
            consume(rabbit_url, KITCHEN, "Kitchen", KitchenHandler(event_db)),
            consume(rabbit_url, DELIVERY, "Delivery", DeliveryPlanner(event_db)),
        ):
            await publish_raw(rabbit_url, "order.paid", paid_body(7))

            async def done():
                with event_db() as db:
                    return kitchen_rows(event_db) == [(7, "pending")] and db.get(DeliveryRequestRow, 7) is not None
            await wait_for(done)
    run(scenario())


def test_duplicate_delivery_creates_no_duplicate(rabbit_url, event_db):
    async def scenario():
        await reset_broker(rabbit_url)
        async with Running(consume(rabbit_url, KITCHEN, "Kitchen", KitchenHandler(event_db))):
            body = paid_body(42, event_id="11111111-1111-1111-1111-111111111111")
            for _ in range(3):
                await publish_raw(rabbit_url, "order.paid", body)
            await publish_raw(rabbit_url, "order.paid", paid_body(43))

            async def done():
                return kitchen_rows(event_db) == [(42, "pending"), (43, "pending")]
            await wait_for(done)
            await asyncio.sleep(0.5)
            assert kitchen_rows(event_db) == [(42, "pending"), (43, "pending")]
    run(scenario())


def test_poison_message_goes_to_dlq_and_queue_keeps_working(rabbit_url, event_db):
    async def scenario():
        await reset_broker(rabbit_url)
        async with Running(consume(rabbit_url, KITCHEN, "Kitchen", KitchenHandler(event_db))):
            await publish_raw(rabbit_url, "order.paid", b"not-json")
            await publish_raw(rabbit_url, "order.paid", paid_body(42))

            async def done():
                return kitchen_rows(event_db) == [(42, "pending")] and await queue_size(rabbit_url, "kitchen_dlq") == 1
            await wait_for(done)
            assert await queue_size(rabbit_url, "kitchen_queue") == 0
    run(scenario())


def test_failing_handler_retried_then_dead_lettered(rabbit_url):
    attempts = []
    spec = QueueSpec("flaky_queue", ("test.flaky",))

    def flaky(routing_key, payload):
        attempts.append(payload["order_id"])
        raise RuntimeError("БД недоступна")

    async def scenario():
        async with Running(consume(rabbit_url, spec, "Flaky", flaky, retry_delay=0.05)):
            await publish_raw(rabbit_url, "test.flaky", paid_body(5))

            async def done():
                return await queue_size(rabbit_url, "flaky_dlq") == 1
            await wait_for(done)
        assert attempts == [5, 5, 5]
    run(scenario())


def test_outbox_waits_while_broker_is_down_then_publishes(rabbit_url, event_db):
    with event_db() as db:
        order_id = OrderService(SqlAlchemyOrderRepository(db), RecordingNotifier()).create_order(1, 1, 1)

    def unpublished():
        with event_db() as db:
            return db.query(OutboxEvent).filter(OutboxEvent.published_at.is_(None)).count()

    async def scenario():
        await reset_broker(rabbit_url)
        # Брокер «упал»: релей не может подключиться, событие ждёт в outbox.
        async with Running(relay_forever("amqp://sirius:sirius@127.0.0.1:1/", event_db, interval=0.1)):
            await asyncio.sleep(1)
            assert unpublished() == 1
        # Брокер «поднялся».
        async with Running(relay_forever(rabbit_url, event_db, interval=0.1),
                           consume(rabbit_url, KITCHEN, "Kitchen", KitchenHandler(event_db))):
            async def done():
                return unpublished() == 0 and kitchen_rows(event_db) == [(order_id, "pending")]
            await wait_for(done)
    run(scenario())


def test_saga_end_to_end_without_couriers(rabbit_url, event_db):
    """Заказ → order.paid → курьеров нет → delivery.failed → отмена, возврат, order.cancelled → кухня."""
    with event_db() as db:
        order_id = OrderService(SqlAlchemyOrderRepository(db), RecordingNotifier()).create_order(1, 1, 1)
        assert db.get(UserModel, 1).balance == 750.0

    async def scenario():
        await reset_broker(rabbit_url)
        async with Running(
            relay_forever(rabbit_url, event_db, interval=0.1),
            consume(rabbit_url, KITCHEN, "Kitchen", KitchenHandler(event_db)),
            consume(rabbit_url, DELIVERY, "Delivery", DeliveryPlanner(event_db)),
            consume(rabbit_url, SAGA, "Saga", SagaHandler(event_db)),
        ):
            async def done():
                return kitchen_rows(event_db) == [(order_id, "cancelled")]
            await wait_for(done)

            # Повторное delivery.failed не вернёт деньги второй раз.
            await publish_raw(rabbit_url, "delivery.failed", json.dumps(
                {"event_id": str(uuid.uuid4()), "order_id": order_id, "reason": "повтор"}).encode())
            await asyncio.sleep(1)

    run(scenario())
    with event_db() as db:
        assert db.get(OrderModel, order_id).status == "cancelled"
        assert db.get(UserModel, 1).balance == 1000.0
        assert db.query(Refund).count() == 1
