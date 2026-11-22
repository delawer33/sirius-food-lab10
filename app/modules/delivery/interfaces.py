"""
Порты модуля delivery.

DeliveryRepository — то, что осталось в монолите: заказы и пользователи.
DeliveryGateway — доставки. После выноса в микросервис ими владеет он,
монолит обращается к ним через этот порт и не знает, что за ним сеть.
"""
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence

from app.domain.entities import Delivery, Order, User
from app.domain.events import DomainEvent


class DeliveryRepository(ABC):
    @abstractmethod
    def get_order(self, order_id: int) -> Order | None:
        """Заказ по идентификатору или None."""

    @abstractmethod
    def get_user_by_id(self, user_id: int) -> User | None:
        """Пользователь по идентификатору или None."""

    @abstractmethod
    def set_order_status(self, order_id: int, status: str, events: Sequence[DomainEvent] = ()) -> None:
        """Сменить статус заказа и в той же транзакции записать события в outbox."""


class DeliveryGateway(ABC):
    """
    Ошибки: NotFoundError, BusinessRuleError (нарушено правило доставки),
    ServiceUnavailableError и ServiceTimeoutError (сервис недоступен).
    """

    @abstractmethod
    def assign(self, order_id: int, courier_id: int) -> Delivery:
        """Создать доставку in_progress. BusinessRuleError, если курьер занят или заказ уже везут."""

    @abstractmethod
    def get(self, delivery_id: int) -> Delivery | None:
        """Доставка по идентификатору или None."""

    @abstractmethod
    def list_by_courier(self, courier_id: int) -> list[Delivery]:
        """Все доставки курьера по возрастанию id."""

    @abstractmethod
    def complete(self, delivery_id: int) -> str:
        """Завершить доставку, вернуть новый статус. BusinessRuleError, если уже завершена или отменена."""

    @abstractmethod
    def track(self, delivery_id: int) -> Iterator[str]:
        """Статусы доставки по мере их смены: in_progress, on_the_way, delivered."""

