"""
Инфраструктурный слой модуля delivery (круг 3: Interface Adapters).

Репозитории — заказы и пользователи монолита.

Шлюзы к доставкам, кроме gRPC (app/infrastructure/delivery_grpc.py):
- SqlAlchemyDeliveryGateway — старый путь, прямо в таблицу deliveries.
  Strangler Fig: остаётся до конца переезда, включается DELIVERY_BACKEND=local,
  если с микросервисом что-то не так. Потом удаляется.
- InMemoryDeliveryGateway — для REPO_BACKEND=memory и тестов.
Правила у них те же, что в delivery_service/core.py; контрактные тесты
гоняют все три шлюза одним набором.
"""
from collections.abc import Iterator, Sequence
from dataclasses import replace

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.entities import (
    DELIVERY_CANCELLED,
    DELIVERY_COMPLETED,
    DELIVERY_IN_PROGRESS,
    Delivery,
    Order,
    User,
)
from app.domain.errors import BusinessRuleError, NotFoundError
from app.domain.events import DomainEvent
from app.infrastructure.memory import InMemoryStorage
from app.infrastructure.outbox import add_to_outbox
from app.infrastructure.sql import user_to_entity
from app.models import Delivery as DeliveryModel
from app.models import Order as OrderModel
from app.models import User as UserModel
from app.modules.delivery.interfaces import DeliveryGateway, DeliveryRepository

BUSY = "У курьера уже есть активная доставка или заказ уже везут"
ALREADY_COMPLETED = "Доставка уже завершена"
CANCELLED = "Отменённую доставку нельзя завершить"
TRACK_STEPS = ("in_progress", "on_the_way", "delivered")


def _to_entity(row: DeliveryModel) -> Delivery:
    return Delivery(id=row.id, order_id=row.order_id, courier_id=row.courier_id, status=row.status)


def _check_can_complete(delivery) -> None:
    if delivery is None:
        raise NotFoundError("Доставка не найдена")
    status = delivery.status
    if status == DELIVERY_COMPLETED:
        raise BusinessRuleError(ALREADY_COMPLETED)
    if status == DELIVERY_CANCELLED:
        raise BusinessRuleError(CANCELLED)


class SqlAlchemyDeliveryRepository(DeliveryRepository):
    def __init__(self, db: Session):
        self.db = db

    def get_order(self, order_id: int) -> Order | None:
        row = self.db.get(OrderModel, order_id)
        if row is None:
            return None
        return Order(row.id, row.user_id, row.item_id, row.quantity, row.status, row.total_cost)

    def get_user_by_id(self, user_id: int) -> User | None:
        row = self.db.get(UserModel, user_id)
        return user_to_entity(row) if row else None

    def set_order_status(self, order_id: int, status: str, events: Sequence[DomainEvent] = ()) -> None:
        self.db.get(OrderModel, order_id).status = status
        add_to_outbox(self.db, events)
        self.db.commit()


class InMemoryDeliveryRepository(DeliveryRepository):
    def __init__(self, storage: InMemoryStorage):
        self.storage = storage

    def get_order(self, order_id: int) -> Order | None:
        order = self.storage.orders.get(order_id)
        return replace(order) if order else None

    def get_user_by_id(self, user_id: int) -> User | None:
        user = self.storage.users.get(user_id)
        return replace(user) if user else None

    def set_order_status(self, order_id: int, status: str, events: Sequence[DomainEvent] = ()) -> None:
        with self.storage.lock:
            self.storage.orders[order_id].status = status
            self.storage.outbox.extend(events)


class SqlAlchemyDeliveryGateway(DeliveryGateway):
    def __init__(self, db: Session):
        self.db = db

    def assign(self, order_id: int, courier_id: int) -> Delivery:
        row = DeliveryModel(order_id=order_id, courier_id=courier_id, status=DELIVERY_IN_PROGRESS)
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError as error:
            self.db.rollback()
            # Уникальные индексы активной доставки (миграция 0005).
            if "foreign key" not in str(error.orig).lower():
                raise BusinessRuleError(BUSY) from None
            raise
        self.db.refresh(row)
        return _to_entity(row)

    def get(self, delivery_id: int) -> Delivery | None:
        row = self.db.get(DeliveryModel, delivery_id)
        return _to_entity(row) if row else None

    def list_by_courier(self, courier_id: int) -> list[Delivery]:
        rows = (
            self.db.query(DeliveryModel)
            .filter(DeliveryModel.courier_id == courier_id)
            .order_by(DeliveryModel.id)
        )
        return [_to_entity(row) for row in rows]

    def complete(self, delivery_id: int) -> str:
        row = self.db.get(DeliveryModel, delivery_id)
        _check_can_complete(row)
        row.status = DELIVERY_COMPLETED
        self.db.commit()
        return row.status

    def track(self, delivery_id: int) -> Iterator[str]:
        """Без микросервиса трекинга нет: только текущий статус."""
        yield self.db.get(DeliveryModel, delivery_id).status


class InMemoryDeliveryGateway(DeliveryGateway):
    def __init__(self, storage: InMemoryStorage):
        self.storage = storage

    def assign(self, order_id: int, courier_id: int) -> Delivery:
        with self.storage.lock:
            if any(
                d.status == DELIVERY_IN_PROGRESS and (d.courier_id == courier_id or d.order_id == order_id)
                for d in self.storage.deliveries.values()
            ):
                raise BusinessRuleError(BUSY)
            delivery_id = self.storage.next_id(self.storage.deliveries)
            delivery = Delivery(delivery_id, order_id, courier_id, DELIVERY_IN_PROGRESS)
            self.storage.deliveries[delivery_id] = delivery
            return replace(delivery)

    def get(self, delivery_id: int) -> Delivery | None:
        delivery = self.storage.deliveries.get(delivery_id)
        return replace(delivery) if delivery else None

    def list_by_courier(self, courier_id: int) -> list[Delivery]:
        return [
            replace(d)
            for _, d in sorted(self.storage.deliveries.items())
            if d.courier_id == courier_id
        ]

    def complete(self, delivery_id: int) -> str:
        with self.storage.lock:
            delivery = self.storage.deliveries.get(delivery_id)
            _check_can_complete(delivery)
            delivery.status = DELIVERY_COMPLETED
            return delivery.status

    def track(self, delivery_id: int) -> Iterator[str]:
        """Те же шаги, что у микросервиса, без пауз."""
        if self.storage.deliveries[delivery_id].status == DELIVERY_COMPLETED:
            yield "delivered"
            return
        yield from TRACK_STEPS
