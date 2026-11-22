"""
Бизнес-сущности предметной области (круг 1 модели Мартина: Entities).

Это обычные dataclass-объекты без зависимостей от ORM и веб-фреймворка.
Репозитории переводят в них строки таблиц, поэтому сервисы работают
с предметной областью, а не с моделями SQLAlchemy.
"""
from dataclasses import dataclass
from datetime import datetime

from app.domain.roles import STUDENT


@dataclass
class User:
    id: int
    email: str
    phone: str | None
    balance: float
    is_blocked: bool
    role: str = STUDENT
    password_hash: str = ""
    # Номер поколения токенов. Увеличивается, когда все сессии пользователя
    # надо завершить: токены со старым номером перестают приниматься.
    token_version: int = 0


@dataclass
class Category:
    id: int
    name: str


@dataclass
class MenuItem:
    id: int
    name: str
    price: float
    is_available: bool
    category_id: int | None = None


@dataclass
class CategoryMenu:
    """Категория вместе с её блюдами — то, что показывает GET /menu/categories/{id}."""

    category: Category
    items: list[MenuItem]


# Статусы заказа: processing -> ready -> delivering -> delivered,
# из processing заказ можно отменить (cancelled).
ORDER_PROCESSING = "processing"
ORDER_READY = "ready"
ORDER_DELIVERING = "delivering"
ORDER_DELIVERED = "delivered"
ORDER_CANCELLED = "cancelled"


@dataclass
class Order:
    id: int
    user_id: int
    item_id: int
    quantity: int
    status: str
    # Сколько списано с баланса. Нужно для возврата при отмене:
    # цена блюда в меню может измениться после заказа.
    total_cost: float = 0.0


DELIVERY_IN_PROGRESS = "in_progress"
DELIVERY_COMPLETED = "completed"
DELIVERY_CANCELLED = "cancelled"


@dataclass
class Delivery:
    id: int
    order_id: int
    courier_id: int
    status: str


@dataclass
class RefreshToken:
    """Выданный refresh-токен. Хранится хеш, сам токен знает только клиент."""

    id: int
    user_id: int
    token_hash: str
    expires_at: datetime
    is_revoked: bool
