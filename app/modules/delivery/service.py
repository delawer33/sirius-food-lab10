"""
Слой бизнес-логики модуля delivery. Без fastapi, sqlalchemy и grpc.

Доставками владеет микросервис, сервис работает с ними через порт
DeliveryGateway. Здесь остались правила, которым нужны заказы и
пользователи монолита:
- курьера назначают на готовый заказ, назначают именно курьера, и он не заблокирован;
- доставку видят назначенный курьер, владелец заказа и администратор (IDOR);
- завершить её может назначенный курьер или администратор.

Жизненный цикл доставки (курьер занят, уже завершена) проверяет микросервис.
"""
from collections.abc import Iterator
from dataclasses import replace

from app.domain.entities import ORDER_DELIVERED, ORDER_DELIVERING, ORDER_READY, Delivery, User
from app.domain.errors import AccessDeniedError, BusinessRuleError, NotFoundError
from app.domain.events import order_delivered
from app.domain.roles import ADMIN, COURIER
from app.modules.delivery.interfaces import DeliveryGateway, DeliveryRepository


class DeliveryService:
    """Бизнес-правила доставки заказов."""

    def __init__(self, repository: DeliveryRepository, gateway: DeliveryGateway):
        self.repository = repository
        self.gateway = gateway

    def assign_courier(self, order_id: int, courier_id: int) -> Delivery:
        """Назначает курьера на готовый заказ."""
        order = self.repository.get_order(order_id)
        if order is None:
            raise NotFoundError("Заказ не найден")

        # Бизнес-правило: курьера назначают на заказ, который кухня приготовила.
        if order.status != ORDER_READY:
            raise BusinessRuleError("Курьера можно назначить только на готовый заказ")

        courier = self.repository.get_user_by_id(courier_id)
        if courier is None:
            raise NotFoundError("Курьер не найден")
        if courier.role != COURIER:
            raise BusinessRuleError("Пользователь не является курьером")
        if courier.is_blocked:
            raise AccessDeniedError("Курьер заблокирован и не может быть назначен")

        delivery = self.gateway.assign(order_id, courier_id)
        # Две базы — две транзакции. Если упадёт эта строка, доставка уже
        # создана, а заказ остался ready. См. README, «Что не решено».
        self.repository.set_order_status(order_id, ORDER_DELIVERING)
        return delivery

    def get_delivery(self, delivery_id: int, actor: User) -> Delivery:
        """Доставку видят назначенный курьер, владелец заказа и администратор."""
        delivery = self._get_existing(delivery_id)
        if actor.role == ADMIN or delivery.courier_id == actor.id:
            return delivery
        order = self.repository.get_order(delivery.order_id)
        if order is not None and order.user_id == actor.id:
            return delivery
        raise AccessDeniedError("Нет доступа к этой доставке")

    def list_my_deliveries(self, actor: User) -> list[Delivery]:
        """Курьер видит только свои доставки."""
        return self.gateway.list_by_courier(actor.id)

    def complete_delivery(self, delivery_id: int, actor: User) -> Delivery:
        """Завершает доставку и переводит заказ в delivered."""
        delivery = self._get_existing(delivery_id)
        if delivery.courier_id != actor.id and actor.role != ADMIN:
            raise AccessDeniedError("Завершить можно только свою доставку")
        status = self.gateway.complete(delivery_id)
        self.repository.set_order_status(
            delivery.order_id, ORDER_DELIVERED,
            events=[order_delivered(delivery.order_id, delivery.id, delivery.courier_id)],
        )
        return replace(delivery, status=status)

    def track_delivery(self, delivery_id: int, actor: User) -> Iterator[str]:
        """Поток статусов. Права те же, что на просмотр, и проверяются сразу."""
        self.get_delivery(delivery_id, actor)
        return self.gateway.track(delivery_id)

    def _get_existing(self, delivery_id: int) -> Delivery:
        delivery = self.gateway.get(delivery_id)
        if delivery is None:
            raise NotFoundError("Доставка не найдена")
        return delivery
