"""
Определение ORM-моделей предметной области «Сириус.Еда».

Схема БД меняется только миграциями Alembic (каталог alembic/versions).
"""
from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Session, relationship

from app.database import Base
from app.domain.roles import ALL_ROLES


class Role(Base):
    """Роль пользователя: student, cook, courier, admin."""

    __tablename__ = "roles"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), unique=True, nullable=False)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False)
    phone = Column(String, nullable=True)
    balance = Column(Float, default=0.0)
    is_blocked = Column(Boolean, default=False)
    # bcrypt-хеш пароля. Сам пароль нигде не хранится.
    password_hash = Column(String, nullable=False)
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=False)
    token_version = Column(Integer, nullable=False, default=0, server_default="0")

    role = relationship("Role", lazy="joined")


class Category(Base):
    """Категория меню: супы, горячее, напитки."""

    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)


class MenuItem(Base):
    __tablename__ = "menu_items"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    is_available = Column(Boolean, default=True)
    # Блюдо может быть вне категорий: так остаются блюда из прошлых лабораторных.
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)

    category = relationship("Category")


class Order(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    item_id = Column(Integer, ForeignKey("menu_items.id"))
    quantity = Column(Integer, nullable=False)
    status = Column(String, default="processing")
    total_cost = Column(Float, nullable=False, default=0.0, server_default="0")
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)

    user = relationship("User")
    item = relationship("MenuItem")


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    courier_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    status = Column(String, default="pending")

    order = relationship("Order")
    courier = relationship("User")

    # Одна активная доставка у курьера, один курьер у заказа (миграция 0005).
    __table_args__ = (
        Index("uq_deliveries_active_courier", "courier_id", unique=True,
              postgresql_where=text("status = 'in_progress'"), sqlite_where=text("status = 'in_progress'")),
        Index("uq_deliveries_active_order", "order_id", unique=True,
              postgresql_where=text("status = 'in_progress'"), sqlite_where=text("status = 'in_progress'")),
    )


class RefreshToken(Base):
    """Refresh-токен для обновления access-токена."""

    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    # Храним хеш токена, а не сам токен — на случай утечки БД.
    token_hash = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_revoked = Column(Boolean, nullable=False, default=False, server_default="false")


class TaskLog(Base):
    """Журнал выполнения фоновых задач. Старые записи чистит Celery Beat."""

    __tablename__ = "task_logs"

    id = Column(Integer, primary_key=True)
    task_id = Column(String, nullable=False)
    task_name = Column(String, nullable=False)
    order_id = Column(Integer, nullable=True, index=True)
    # success, skipped (идемпотентность), retry, failed (ушла в DLQ)
    status = Column(String, nullable=False)
    detail = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)


class OrderStats(Base):
    """Статистика заказов за день. Пересчитывает периодическая задача Celery Beat."""

    __tablename__ = "order_stats"

    day = Column(Date, primary_key=True)
    orders_count = Column(Integer, nullable=False)
    # Выручка без отменённых заказов.
    revenue = Column(Float, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class OutboxEvent(Base):
    """
    Transactional Outbox: событие пишется сюда в одной транзакции с заказом,
    в RabbitMQ его переносит app/workers/outbox_relay.py.
    """

    __tablename__ = "outbox"

    id = Column(Integer, primary_key=True)
    event_id = Column(String(36), unique=True, nullable=False)
    routing_key = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    # NULL — ещё не опубликовано. Частичный индекс: релей ищет только такие.
    published_at = Column(DateTime, nullable=True)
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(String, nullable=True)
    # Контекст запроса, породившего событие: релей кладёт их в заголовки сообщения.
    correlation_id = Column(String(128), nullable=True)
    trace_context = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_outbox_unpublished", "id",
              postgresql_where=text("published_at IS NULL"), sqlite_where=text("published_at IS NULL")),
    )


class ProcessedEvent(Base):
    """Обработанные consumer'ом события: повторная доставка с тем же event_id пропускается."""

    __tablename__ = "processed_events"

    consumer = Column(String, primary_key=True)
    event_id = Column(String(36), primary_key=True)
    processed_at = Column(DateTime, nullable=False, server_default=func.now())


class KitchenOrder(Base):
    """Очередь кухни, которую ведёт consumer по событиям order.paid и order.cancelled."""

    __tablename__ = "kitchen_orders"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, unique=True, nullable=False)
    status = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class Refund(Base):
    """
    Возврат денег за отменённый заказ. order_id уникален — это ключ
    компенсации: второй возврат за тот же заказ БД не примет.
    """

    __tablename__ = "refunds"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"), unique=True, nullable=False)
    amount = Column(Float, nullable=False)
    reason = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


def seed_roles(session: Session) -> None:
    """Заполняет справочник ролей. В рабочей БД это делает миграция."""
    existing = {name for (name,) in session.query(Role.name)}
    session.add_all(Role(name=name) for name in ALL_ROLES if name not in existing)
    session.commit()
