"""
Хранилище в памяти процесса для in-memory реализаций репозиториев.

Одно хранилище общее для всех модулей, как одна база данных: заказ видит
пользователей и блюда, созданные через другие модули. Наружу отдаются
копии сущностей, чтобы изменение объекта без вызова репозитория ничего
не меняло — так же, как с записью в СУБД.
"""
import threading
from dataclasses import dataclass, field

from app.domain.entities import Category, Delivery, MenuItem, Order, RefreshToken, User
from app.domain.events import DomainEvent


@dataclass
class InMemoryStorage:
    users: dict[int, User] = field(default_factory=dict)
    menu_items: dict[int, MenuItem] = field(default_factory=dict)
    categories: dict[int, Category] = field(default_factory=dict)
    orders: dict[int, Order] = field(default_factory=dict)
    deliveries: dict[int, Delivery] = field(default_factory=dict)
    refresh_tokens: dict[int, RefreshToken] = field(default_factory=dict)
    # Аналог таблицы outbox: в режиме memory события никуда не уходят,
    # список нужен тестам.
    outbox: list[DomainEvent] = field(default_factory=list)
    # order_id -> сумма возврата, аналог таблицы refunds.
    refunds: dict[int, float] = field(default_factory=dict)
    # FastAPI выполняет синхронные обработчики в пуле потоков.
    lock: threading.RLock = field(default_factory=threading.RLock)

    def next_id(self, table: dict) -> int:
        """Аналог автоинкремента первичного ключа."""
        return max(table, default=0) + 1
