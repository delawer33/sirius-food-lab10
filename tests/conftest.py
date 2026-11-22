import os

# Настройки фиксируются до импорта приложения, чтобы тесты не зависели от
# локального .env: SQLite в памяти вместо PostgreSQL, продакшен-режим.
os.environ.update(
    DATABASE_URL="sqlite://",
    SECRET_KEY="test-secret-key-that-is-long-enough-for-hs256",
    DEBUG="false",
    ALLOWED_ORIGINS='["https://sirius-food.ru"]',
    REPO_BACKEND="sql",
    RATE_LIMIT_ENABLED="true",
    # Имитация тяжёлых операций в тестах не нужна.
    PDF_DELAY="0",
    EMAIL_DELAY="0",
    SMS_DELAY="0",
)

import fakeredis  # noqa: E402
import grpc  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import container  # noqa: E402
from app.core import security  # noqa: E402
from app.core.jwt import create_access_token  # noqa: E402
from app.core.redis import get_redis  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.infrastructure.memory import InMemoryStorage  # noqa: E402
from app.main import app  # noqa: E402
from app.models import MenuItem, Role, User, seed_roles  # noqa: E402
from delivery_service.storage import Base as DeliveryBase  # noqa: E402
from tests.fakes import RecordingNotifier  # noqa: E402
from app.infrastructure.delivery_grpc import CHANNEL_OPTIONS, GrpcDeliveryGateway  # noqa: E402
from delivery_service.chat import ChatHub  # noqa: E402
from delivery_service.core import DeliveryCore  # noqa: E402
from delivery_service.server import build_server  # noqa: E402
from delivery_service.storage import DeliveryStore, make_session_factory  # noqa: E402
from app.modules.users.repository import InMemoryUserRepository, SqlAlchemyUserRepository  # noqa: E402
from app.modules.users.service import UserService  # noqa: E402

PASSWORD = "test-password"

# bcrypt с cost 12 считает хеш ~0,2 с. Для тестов стойкость не нужна.
security.pwd_context.update(bcrypt__rounds=4)


def reset_sql_schema() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with Session(engine) as session:
        seed_roles(session)


@pytest.fixture
def db_session():
    """Сессия к чистой SQLite-базе в памяти со справочником ролей."""
    reset_sql_schema()
    with Session(engine) as session:
        yield session


@pytest.fixture
def event_db():
    """Чистая SQLite-база: таблицы монолита и сервиса доставки, студент с 1000 ₽, борщ за 250."""
    DeliveryBase.metadata.drop_all(engine)
    reset_sql_schema()
    DeliveryBase.metadata.create_all(engine)
    with SessionLocal() as db:
        student = db.query(Role).filter_by(name="student").one()
        db.add(User(id=1, email="anna@sirius.ru", balance=1000.0, password_hash="h", role_id=student.id))
        db.add(MenuItem(id=1, name="Борщ", price=250.0))
        db.commit()
    return SessionLocal


@pytest.fixture
def storage():
    return InMemoryStorage()


@pytest.fixture
def redis():
    # Свой сервер на каждый тест: кеш и счётчики не переходят между тестами.
    return fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)


class DeliveryServer:
    """Настоящий gRPC-сервер доставки в этом же процессе, на свободном порту."""

    def __init__(self):
        self.store = DeliveryStore(make_session_factory("sqlite://"))
        self.hub = ChatHub()
        self.server, self.port = build_server(
            DeliveryCore(self.store), self.hub, "127.0.0.1:0", track_interval=0.05
        )
        self.server.start()
        self.channel = grpc.insecure_channel(f"127.0.0.1:{self.port}", options=CHANNEL_OPTIONS)

    def reset(self) -> None:
        self.store.drop_schema()
        self.store.create_schema()
        # Сервер общий на все тесты, а id доставок начинаются заново:
        # история чата прошлого теста не должна попасть в новый.
        self.hub.__init__()

    def stop(self) -> None:
        self.channel.close()
        self.server.stop(0)


@pytest.fixture(scope="session")
def delivery_server_session():
    server = DeliveryServer()
    yield server
    server.stop()


@pytest.fixture
def delivery_server(delivery_server_session):
    """Сервер доставки с пустой таблицей."""
    delivery_server_session.reset()
    return delivery_server_session


@pytest.fixture
def grpc_gateway(delivery_server):
    return GrpcDeliveryGateway(delivery_server.channel, timeout=2.0)


@pytest.fixture(params=["sql", "memory"])
def api(request, monkeypatch, redis, delivery_server):
    """
    Клиент API на чистом хранилище. Тест с этой фикстурой запускается
    дважды: на SQLAlchemy и на in-memory репозиториях. В варианте sql
    доставки идут в настоящий gRPC-сервер, как в продакшене.
    """
    reset_sql_schema()
    memory = InMemoryStorage()
    monkeypatch.setattr(container, "REPO_BACKEND", request.param)
    monkeypatch.setattr(container, "memory_storage", memory)
    if request.param == "sql":
        gateway = GrpcDeliveryGateway(delivery_server.channel, timeout=2.0)
        app.dependency_overrides[container.get_delivery_gateway] = lambda: gateway
    app.dependency_overrides[get_redis] = lambda: redis
    notifier = RecordingNotifier()
    app.dependency_overrides[container.get_order_notifier] = lambda: notifier
    yield Api(TestClient(app), request.param, memory, notifier)
    app.dependency_overrides.clear()


class Api:
    """Клиент и помощники: завести пользователя, получить его токен."""

    def __init__(
        self, client: TestClient, backend: str, memory: InMemoryStorage, notifier: RecordingNotifier
    ):
        self.client = client
        self.backend = backend
        self.memory = memory
        # Какие заказы отправлены в фоновую обработку.
        self.notifier = notifier

    def create_user(
        self, email: str, role: str = "student", balance: float = 0.0, password: str = PASSWORD
    ):
        """Пользователь в обход API — так же, как его создаёт scripts/create_user.py."""
        if self.backend == "memory":
            return self._create(UserService(InMemoryUserRepository(self.memory)), email, role, balance, password)
        with SessionLocal() as session:
            return self._create(UserService(SqlAlchemyUserRepository(session)), email, role, balance, password)

    @staticmethod
    def _create(service: UserService, email: str, role: str, balance: float, password: str):
        user = service.create_user(email, password, role)
        if balance:
            service.repository.update_balance(user.id, balance)
            user.balance = balance
        return user

    def headers(self, user) -> dict:
        """Заголовок с access-токеном. Логин через API проверяется отдельно."""
        return {"Authorization": f"Bearer {create_access_token(user.id, user.token_version)}"}

    def login(self, email: str, password: str = PASSWORD):
        return self.client.post("/auth/login", json={"email": email, "password": password})
