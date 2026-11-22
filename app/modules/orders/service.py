"""
Слой бизнес-логики модуля orders (круги 1–2: Entities и Use Cases).

Импорты fastapi и sqlalchemy здесь запрещены. Хранилище приходит снаружи
через конструктор, поэтому сервис можно вызывать из HTTP, CLI или фоновой
задачи и тестировать без СУБД.

Защита от IDOR — здесь: «этот заказ принадлежит этому пользователю» — правило
предметной области, оно должно работать при любом способе вызова сервиса.
"""
from app.domain.entities import (
    ORDER_CANCELLED,
    ORDER_PROCESSING,
    ORDER_READY,
    Order,
    User,
)
from app.domain.errors import AccessDeniedError, AlreadyRefundedError, BusinessRuleError, NotFoundError
from app.domain.events import order_cancelled, order_paid
from app.domain.roles import ADMIN, COOK
from app.modules.orders.interfaces import OrderNotifier, OrderRepository

# Кто кроме владельца может смотреть любой заказ.
STAFF_VIEWERS = (COOK, ADMIN)
# Статусы, в которых заказ ещё можно отменить с возвратом денег, если
# доставку организовать не удалось (компенсация саги).
COMPENSABLE = (ORDER_PROCESSING, ORDER_READY)


class OrderService:
    """Бизнес-правила оформления, просмотра, отмены и готовки заказа."""

    def __init__(self, repository: OrderRepository, notifier: OrderNotifier):
        # Внедрение зависимостей через конструктор.
        self.repository = repository
        self.notifier = notifier

    def create_order(self, user_id: int, item_id: int, quantity: int) -> int:
        """
        Сценарий оформления заказа. Возвращает идентификатор заказа.
        user_id приходит из токена, а не из тела запроса.
        Возбуждает NotFoundError или BusinessRuleError при нарушении правил.
        """
        user = self.repository.get_user_by_id(user_id)
        if user is None:
            raise NotFoundError("Пользователь не найден")

        item = self.repository.get_menu_item_by_id(item_id)
        if item is None:
            raise NotFoundError("Блюдо не найдено")
        if not item.is_available:
            raise BusinessRuleError("Блюдо недоступно")

        total_cost = item.price * quantity
        if user.balance < total_cost:
            raise BusinessRuleError("Недостаточно средств на балансе студента")

        order_id = self.repository.save_order(
            user_id=user_id,
            item_id=item_id,
            quantity=quantity,
            total_cost=total_cost,
            new_balance=user.balance - total_cost,
            # Деньги списаны при оформлении — заказ оплачен. Событие ляжет
            # в outbox той же транзакцией, в RabbitMQ его отнесёт релей.
            make_events=lambda new_id: [order_paid(new_id, user_id, total_cost)],
        )
        # Бизнес-правило: после оформления — чек и уведомления. Заказ уже
        # сохранён, поэтому воркер найдёт его, даже если начнёт сразу.
        self.notifier.order_created(order_id, user.email, user.phone)
        return order_id

    def get_order(self, order_id: int, actor: User) -> Order:
        """Заказ видят его владелец, повар и администратор."""
        order = self._get_existing(order_id)
        if order.user_id != actor.id and actor.role not in STAFF_VIEWERS:
            raise AccessDeniedError("Нет доступа к этому заказу")
        return order

    def list_my_orders(self, actor: User) -> list[Order]:
        return self.repository.list_orders_by_user(actor.id)

    def cancel_order(self, order_id: int, actor: User) -> Order:
        """
        Отменяет заказ и возвращает деньги. Отменить можно только свой заказ
        (администратор — любой) и только пока кухня его не приготовила.
        """
        order = self._get_existing(order_id)
        if order.user_id != actor.id and actor.role != ADMIN:
            raise AccessDeniedError("Нельзя отменить чужой заказ")
        if order.status != ORDER_PROCESSING:
            raise BusinessRuleError("Отменить можно только заказ, который ещё готовится")

        return self._cancel_with_refund(order, reason="client")

    def compensate_failed_delivery(self, order_id: int) -> Order | None:
        """
        Компенсация саги: доставку организовать не удалось — отменяем заказ,
        возвращаем деньги, публикуем order.cancelled. Идемпотентна: уже
        отменённый заказ не трогает и возвращает None.
        """
        order = self._get_existing(order_id)
        if order.status not in COMPENSABLE:
            return None
        try:
            return self._cancel_with_refund(order, reason="delivery_failed")
        except AlreadyRefundedError:
            return None

    def _cancel_with_refund(self, order: Order, reason: str) -> Order:
        owner = self.repository.get_user_by_id(order.user_id)
        return self.repository.cancel_order(
            order.id,
            ORDER_CANCELLED,
            new_balance=owner.balance + order.total_cost,
            reason=reason,
            events=[order_cancelled(order.id, order.user_id, order.total_cost, reason)],
        )

    def get_kitchen_orders(self) -> list[Order]:
        """Очередь кухни: заказы, которые надо приготовить."""
        return self.repository.list_orders_by_status(ORDER_PROCESSING)

    def mark_ready(self, order_id: int) -> Order:
        """Кухня приготовила заказ: теперь на него можно назначить курьера."""
        order = self._get_existing(order_id)
        if order.status != ORDER_PROCESSING:
            raise BusinessRuleError("Готовым можно отметить только заказ, который готовится")
        return self.repository.set_order_status(order_id, ORDER_READY)

    def _get_existing(self, order_id: int) -> Order:
        order = self.repository.get_order(order_id)
        if order is None:
            raise NotFoundError("Заказ не найден")
        return order
