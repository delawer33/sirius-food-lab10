"""
Инфраструктурный слой модуля orders (круг 3: Interface Adapters).

Две взаимозаменяемые реализации OrderRepository:
SqlAlchemyOrderRepository — PostgreSQL/SQLite через ORM,
InMemoryOrderRepository — словари в памяти процесса.
Бизнес-правил здесь нет: только чтение и запись.
"""
from collections.abc import Sequence
from dataclasses import replace

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import MenuItem, Order, User
from app.domain.errors import AlreadyRefundedError
from app.domain.events import DomainEvent
from app.infrastructure.memory import InMemoryStorage
from app.infrastructure.outbox import add_to_outbox
from app.infrastructure.sql import user_to_entity
from app.models import MenuItem as MenuItemModel
from app.models import Order as OrderModel
from app.models import Refund
from app.models import User as UserModel
from app.modules.orders.interfaces import EventsFactory, OrderRepository

ALREADY_REFUNDED = "Деньги за этот заказ уже возвращены"


def _order_to_entity(row: OrderModel) -> Order:
    return Order(
        id=row.id,
        user_id=row.user_id,
        item_id=row.item_id,
        quantity=row.quantity,
        status=row.status,
        total_cost=row.total_cost,
    )


class SqlAlchemyOrderRepository(OrderRepository):
    def __init__(self, db: Session):
        self.db = db

    def get_user_by_id(self, user_id: int) -> User | None:
        row = self.db.get(UserModel, user_id)
        return user_to_entity(row) if row else None

    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None:
        row = self.db.get(MenuItemModel, item_id)
        if row is None:
            return None
        return MenuItem(
            id=row.id,
            name=row.name,
            price=row.price,
            is_available=row.is_available,
        )

    def save_order(
        self, user_id: int, item_id: int, quantity: int, total_cost: float, new_balance: float,
        make_events: EventsFactory = lambda order_id: (),
    ) -> int:
        user = self.db.get(UserModel, user_id)
        user.balance = new_balance
        order = OrderModel(
            user_id=user_id,
            item_id=item_id,
            quantity=quantity,
            status="processing",
            total_cost=total_cost,
        )
        self.db.add(order)
        # flush выдаёт id заказа, не завершая транзакцию: событие с этим id
        # попадёт в outbox тем же commit.
        self.db.flush()
        add_to_outbox(self.db, make_events(order.id))
        self.db.commit()
        self.db.refresh(order)
        return order.id

    def get_order(self, order_id: int) -> Order | None:
        row = self.db.get(OrderModel, order_id)
        return _order_to_entity(row) if row else None

    def list_orders_by_user(self, user_id: int) -> list[Order]:
        rows = self.db.query(OrderModel).filter(OrderModel.user_id == user_id).order_by(OrderModel.id)
        return [_order_to_entity(row) for row in rows]

    def list_orders_by_status(self, status: str) -> list[Order]:
        rows = self.db.query(OrderModel).filter(OrderModel.status == status).order_by(OrderModel.id)
        return [_order_to_entity(row) for row in rows]

    def set_order_status(self, order_id: int, status: str) -> Order:
        row = self.db.get(OrderModel, order_id)
        row.status = status
        self.db.commit()
        self.db.refresh(row)
        return _order_to_entity(row)

    def cancel_order(
        self, order_id: int, status: str, new_balance: float,
        reason: str = "client", events: Sequence[DomainEvent] = (),
    ) -> Order:
        row = self.db.get(OrderModel, order_id)
        row.status = status
        self.db.get(UserModel, row.user_id).balance = new_balance
        self.db.add(Refund(order_id=order_id, amount=row.total_cost, reason=reason))
        add_to_outbox(self.db, events)
        try:
            self.db.commit()
        except IntegrityError:
            # Уникальный refunds.order_id: возврат уже был, откатываем всё.
            self.db.rollback()
            raise AlreadyRefundedError(ALREADY_REFUNDED) from None
        self.db.refresh(row)
        return _order_to_entity(row)


class InMemoryOrderRepository(OrderRepository):
    def __init__(self, storage: InMemoryStorage):
        self.storage = storage

    def get_user_by_id(self, user_id: int) -> User | None:
        user = self.storage.users.get(user_id)
        return replace(user) if user else None

    def get_menu_item_by_id(self, item_id: int) -> MenuItem | None:
        item = self.storage.menu_items.get(item_id)
        return replace(item) if item else None

    def save_order(
        self, user_id: int, item_id: int, quantity: int, total_cost: float, new_balance: float,
        make_events: EventsFactory = lambda order_id: (),
    ) -> int:
        with self.storage.lock:
            order_id = self.storage.next_id(self.storage.orders)
            self.storage.orders[order_id] = Order(
                id=order_id,
                user_id=user_id,
                item_id=item_id,
                quantity=quantity,
                status="processing",
                total_cost=total_cost,
            )
            self.storage.users[user_id].balance = new_balance
            self.storage.outbox.extend(make_events(order_id))
            return order_id

    def get_order(self, order_id: int) -> Order | None:
        order = self.storage.orders.get(order_id)
        return replace(order) if order else None

    def list_orders_by_user(self, user_id: int) -> list[Order]:
        return [replace(o) for _, o in sorted(self.storage.orders.items()) if o.user_id == user_id]

    def list_orders_by_status(self, status: str) -> list[Order]:
        return [replace(o) for _, o in sorted(self.storage.orders.items()) if o.status == status]

    def set_order_status(self, order_id: int, status: str) -> Order:
        with self.storage.lock:
            self.storage.orders[order_id].status = status
            return replace(self.storage.orders[order_id])

    def cancel_order(
        self, order_id: int, status: str, new_balance: float,
        reason: str = "client", events: Sequence[DomainEvent] = (),
    ) -> Order:
        with self.storage.lock:
            order = self.storage.orders[order_id]
            if order_id in self.storage.refunds:
                raise AlreadyRefundedError(ALREADY_REFUNDED)
            order.status = status
            self.storage.users[order.user_id].balance = new_balance
            self.storage.refunds[order_id] = order.total_cost
            self.storage.outbox.extend(events)
            return replace(order)
