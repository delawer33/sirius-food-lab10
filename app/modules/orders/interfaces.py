"""
Абстрактный интерфейс хранилища для модуля orders.

Интерфейс принадлежит слою бизнес-логики: сервис описывает, что ему нужно,
а инфраструктура это реализует (принцип инверсии зависимостей).
"""
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence

from app.domain.entities import MenuItem, Order, User
from app.domain.events import DomainEvent

# Получает id нового заказа, возвращает события о нём.
EventsFactory = Callable[[int], Sequence[DomainEvent]]


class OrderRepository(ABC):
    @abstractmethod
    def get_user_by_id(self, user_id: int) -> User | None:
        """Пользователь по идентификатору или None."""

    @abstractmethod
    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None:
        """Блюдо по идентификатору или None."""

    @abstractmethod
    def save_order(
        self, user_id: int, item_id: int, quantity: int, total_cost: float, new_balance: float,
        make_events: EventsFactory = lambda order_id: (),
    ) -> int:
        """
        Атомарно создаёт заказ со статусом processing, записывает новый баланс
        и события make_events(order_id) в outbox.
        """

    @abstractmethod
    def get_order(self, order_id: int) -> Order | None:
        """Заказ по идентификатору или None."""

    @abstractmethod
    def list_orders_by_user(self, user_id: int) -> list[Order]:
        """Заказы пользователя по возрастанию id."""

    @abstractmethod
    def list_orders_by_status(self, status: str) -> list[Order]:
        """Заказы в заданном статусе по возрастанию id."""

    @abstractmethod
    def set_order_status(self, order_id: int, status: str) -> Order:
        """Меняет статус заказа."""

    @abstractmethod
    def cancel_order(
        self, order_id: int, status: str, new_balance: float,
        reason: str = "client", events: Sequence[DomainEvent] = (),
    ) -> Order:
        """
        Атомарно ставит заказу статус отмены, возвращает деньги владельцу,
        записывает возврат и события в outbox. Возврат за заказ бывает один:
        второй — AlreadyRefundedError, ничего не меняется.
        """


class OrderNotifier(ABC):
    """
    Что сделать после оформления заказа: чек, письмо, SMS. Сервис решает,
    КОГДА это нужно (бизнес-правило), а КАК — в фоне через Celery или прямо
    в запросе — решает реализация из app/infrastructure/notifications.py.
    """

    @abstractmethod
    def order_created(self, order_id: int, email: str, phone: str | None) -> None:
        """Запустить обработку нового заказа. Не должен бросать исключений."""
