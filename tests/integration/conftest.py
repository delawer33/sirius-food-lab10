"""
Интеграционные тесты на настоящем PostgreSQL. Testcontainers поднимает пустую
базу в Docker один раз на сессию, схему накатывает Alembic — та же, что в проде.

Изоляция: перед каждым тестом все таблицы, кроме alembic_version и справочника
ролей, очищаются TRUNCATE ... RESTART IDENTITY. Откат транзакции, как в
методичке, здесь не подходит: обработчик заказа сам делает commit.

Без Docker тесты пропускаются.
"""

import os
import subprocess
import sys

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from testcontainers.postgres import PostgresContainer

from app import container
from app.core.jwt import create_access_token
from app.core.redis import get_redis
from app.database import get_db
from app.main import app
from app.models import MenuItem, Role, User
from tests.fakes import RecordingNotifier

POSTGRES_IMAGE = "postgres:16-alpine"  # как в docker-compose.yml
KEEP_TABLES = ("alembic_version", "roles")


@pytest.fixture(scope="session")
def postgres_url():
    """Пустой PostgreSQL в Docker на всю сессию, схема — миграциями Alembic."""
    # Ryuk — контейнер-уборщик testcontainers. Контейнер и так
    # останавливается в конце сессии, лишний образ не нужен.
    os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")
    try:
        container_ = PostgresContainer(POSTGRES_IMAGE, driver="psycopg2")
        container_.start()
    except Exception as error:  # нет Docker или образа
        pytest.skip(f"PostgreSQL в Docker недоступен: {error}")
    url = container_.get_connection_url()
    try:
        # Отдельный процесс: настройки приложения в тестах уже прочитаны
        # (SQLite из tests/conftest.py), а alembic/env.py берёт DATABASE_URL из окружения.
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env={**os.environ, "DATABASE_URL": url},
            check=True,
        )
        yield url
    finally:
        container_.stop()


@pytest.fixture(scope="session")
def pg_engine(postgres_url):
    engine = create_engine(postgres_url, pool_size=10)
    yield engine
    engine.dispose()


@pytest.fixture
def pg(pg_engine):
    """Фабрика сессий к чистой базе: данных нет, роли на месте, id с единицы."""
    with pg_engine.begin() as conn:
        tables = (
            conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
            .scalars()
            .all()
        )
        to_clear = [t for t in tables if t not in KEEP_TABLES]
        conn.execute(text(f"TRUNCATE {', '.join(to_clear)} RESTART IDENTITY CASCADE"))
    return sessionmaker(bind=pg_engine, autoflush=False)


@pytest.fixture
def notifier():
    return RecordingNotifier()


@pytest.fixture
def client(pg, notifier):
    """
    Клиент API, у которого get_db отдаёт сессию к PostgreSQL. Каждый запрос
    получает свою сессию, как в проде, — это важно для теста на гонку.
    Redis заменён на fakeredis, Celery — на RecordingNotifier.
    """

    def pg_db():
        with pg() as session:
            yield session

    app.dependency_overrides[get_db] = pg_db
    app.dependency_overrides[get_redis] = lambda: fakeredis.FakeRedis(
        decode_responses=True
    )
    app.dependency_overrides[container.get_order_notifier] = lambda: notifier
    yield TestClient(app)
    app.dependency_overrides.clear()


def add_student(
    session: Session, email: str = "anna@sirius.ru", balance: float = 1000.0
) -> User:
    student = session.query(Role).filter_by(name="student").one()
    user = User(email=email, balance=balance, password_hash="!", role_id=student.id)
    session.add(user)
    session.commit()
    return user


def add_item(session: Session, name: str = "Сырники", price: float = 150.0) -> MenuItem:
    item = MenuItem(name=name, price=price, is_available=True)
    session.add(item)
    session.commit()
    return item


def auth(user: User) -> dict:
    return {
        "Authorization": f"Bearer {create_access_token(user.id, user.token_version)}"
    }
