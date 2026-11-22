"""
Хранилище сервиса доставки: только таблица deliveries.

Своя модель, а не app.models: сервис не знает о заказах и пользователях
монолита. Внешние ключи на orders и users остались в БД от миграций монолита,
здесь они не объявлены: при переезде в отдельную базу их не станет.
"""
from dataclasses import dataclass

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, create_engine, func, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

IN_PROGRESS = "in_progress"
COMPLETED = "completed"
CANCELLED = "cancelled"
# Статус заявки delivery_requests после назначения курьера.
ASSIGNED = "assigned"

Base = declarative_base()

_ACTIVE = text(f"status = '{IN_PROGRESS}'")


class DeliveryRow(Base):
    __tablename__ = "deliveries"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer)
    courier_id = Column(Integer, nullable=True)
    status = Column(String, default="pending")

    # Правила «одна активная доставка у курьера» и «заказ везёт один курьер»
    # держит БД: проверка в коде не спасает от двух одновременных запросов.
    # Те же индексы создаёт миграция 0005.
    __table_args__ = (
        Index("uq_deliveries_active_courier", "courier_id", unique=True,
              postgresql_where=_ACTIVE, sqlite_where=_ACTIVE),
        Index("uq_deliveries_active_order", "order_id", unique=True,
              postgresql_where=_ACTIVE, sqlite_where=_ACTIVE),
    )


class CourierShiftRow(Base):
    """Кто из курьеров сейчас на смене. Курьеров берёт на смену сервис доставки."""

    __tablename__ = "courier_shifts"

    courier_id = Column(Integer, primary_key=True, autoincrement=False)
    on_shift = Column(Boolean, nullable=False, default=True)


class DeliveryRequestRow(Base):
    """Заявка на доставку, созданная по событию order.paid."""

    __tablename__ = "delivery_requests"

    order_id = Column(Integer, primary_key=True, autoincrement=False)
    # waiting_courier — курьер есть, ждём, пока кухня приготовит;
    # no_courier — курьера не нашлось, отправлено delivery.failed.
    status = Column(String, nullable=False)
    free_couriers = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class DeliveryProcessedEventRow(Base):
    """События, которые consumer доставки уже обработал (идемпотентность)."""

    __tablename__ = "delivery_processed_events"

    event_id = Column(String(36), primary_key=True)
    processed_at = Column(DateTime, nullable=False, server_default=func.now())


# Таблицы, которыми владеет только сервис: монолит их не объявляет,
# alembic check их пропускает (alembic/env.py).
OWN_TABLES = ("courier_shifts", "delivery_requests", "delivery_processed_events")


@dataclass(frozen=True)
class DeliveryRecord:
    id: int
    order_id: int
    courier_id: int
    status: str


class ActiveDeliveryExists(Exception):
    """Нарушен уникальный индекс активной доставки."""


def make_session_factory(url: str) -> sessionmaker:
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    pool_args = {"poolclass": StaticPool} if url in ("sqlite://", "sqlite:///:memory:") else {}
    engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True, **pool_args)
    return sessionmaker(bind=engine, autoflush=False)


def _record(row: DeliveryRow) -> DeliveryRecord:
    return DeliveryRecord(row.id, row.order_id, row.courier_id, row.status)


class DeliveryStore:
    def __init__(self, session_factory: sessionmaker):
        self.session_factory = session_factory

    def create_schema(self) -> None:
        """Для тестов. В PostgreSQL таблицу создают миграции монолита."""
        Base.metadata.create_all(self.session_factory.kw["bind"])

    def drop_schema(self) -> None:
        Base.metadata.drop_all(self.session_factory.kw["bind"])

    def get(self, delivery_id: int) -> DeliveryRecord | None:
        with self.session_factory() as db:
            row = db.get(DeliveryRow, delivery_id)
            return _record(row) if row else None

    def get_by_order(self, order_id: int) -> DeliveryRecord | None:
        """Последняя доставка заказа: после отмены заказ могут назначить заново."""
        with self.session_factory() as db:
            row = (db.query(DeliveryRow).filter(DeliveryRow.order_id == order_id)
                   .order_by(DeliveryRow.id.desc()).first())
            return _record(row) if row else None

    def list_by_courier(self, courier_id: int) -> list[DeliveryRecord]:
        with self.session_factory() as db:
            rows = (db.query(DeliveryRow).filter(DeliveryRow.courier_id == courier_id)
                    .order_by(DeliveryRow.id))
            return [_record(row) for row in rows]

    def create(self, order_id: int, courier_id: int) -> DeliveryRecord:
        with self.session_factory() as db:
            row = DeliveryRow(order_id=order_id, courier_id=courier_id, status=IN_PROGRESS)
            db.add(row)
            # Заявка из order.paid закрыта: курьер назначен.
            db.query(DeliveryRequestRow).filter_by(order_id=order_id).update({"status": ASSIGNED})
            try:
                db.commit()
            except IntegrityError as error:
                db.rollback()
                # Внешний ключ на несуществующий заказ — тоже IntegrityError,
                # но это не «курьер занят».
                if "foreign key" not in str(error.orig).lower():
                    raise ActiveDeliveryExists from error
                raise
            return _record(row)

    def set_status(self, delivery_id: int, status: str) -> DeliveryRecord:
        with self.session_factory() as db:
            row = db.get(DeliveryRow, delivery_id)
            row.status = status
            db.commit()
            return _record(row)
