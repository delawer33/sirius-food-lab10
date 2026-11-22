"""
Бизнес-правила доставки, которые переехали из монолита: жизненный цикл
доставки и «один курьер — одна активная доставка». Без gRPC: сервер только
переводит вызовы и ошибки.

Правила про заказ и пользователя (заказ готов, это курьер, он не заблокирован,
кто видит доставку) остались в монолите: там живут заказы и пользователи.
"""
from delivery_service.storage import (
    CANCELLED,
    COMPLETED,
    ActiveDeliveryExists,
    DeliveryRecord,
    DeliveryStore,
)


class NotFound(Exception):
    pass


class Conflict(Exception):
    """Операция невозможна в текущем состоянии доставки."""


class DeliveryCore:
    def __init__(self, store: DeliveryStore):
        self.store = store

    def assign(self, order_id: int, courier_id: int) -> DeliveryRecord:
        try:
            return self.store.create(order_id, courier_id)
        except ActiveDeliveryExists:
            raise Conflict("У курьера уже есть активная доставка или заказ уже везут") from None

    def complete(self, delivery_id: int) -> DeliveryRecord:
        delivery = self.get(delivery_id)
        if delivery.status == COMPLETED:
            raise Conflict("Доставка уже завершена")
        if delivery.status == CANCELLED:
            raise Conflict("Отменённую доставку нельзя завершить")
        return self.store.set_status(delivery_id, COMPLETED)

    def get(self, delivery_id: int) -> DeliveryRecord:
        delivery = self.store.get(delivery_id)
        if delivery is None:
            raise NotFound("Доставка не найдена")
        return delivery

    def get_by_order(self, order_id: int) -> DeliveryRecord:
        delivery = self.store.get_by_order(order_id)
        if delivery is None:
            raise NotFound("Доставка не найдена")
        return delivery

    def list_by_courier(self, courier_id: int) -> list[DeliveryRecord]:
        return self.store.list_by_courier(courier_id)
