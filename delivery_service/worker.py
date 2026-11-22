"""
Consumer сервиса доставки: по событию order.paid готовит доставку.

    python delivery_worker.py

Есть свободный курьер на смене — заявка waiting_courier, курьера назначат,
когда кухня приготовит заказ. Нет — заявка no_courier и событие
delivery.failed: дальше сага в монолите отменит заказ и вернёт деньги.

У delivery.failed детерминированный event_id (uuid5 от номера заказа).
Если сервис упал после commit, но до публикации, при повторной доставке
order.paid событие уйдёт снова с тем же id — сага не вернёт деньги дважды.
"""
import asyncio
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from delivery_service.config import DeliverySettings
from delivery_service.storage import (
    IN_PROGRESS,
    CourierShiftRow,
    DeliveryProcessedEventRow,
    DeliveryRequestRow,
    DeliveryRow,
    make_session_factory,
)
from messaging.consumer import Outcome, consume, short
from messaging.topology import DELIVERY
import observability
from observability import tracing

WAITING_COURIER = "waiting_courier"
NO_COURIER = "no_courier"
DELIVERY_FAILED = "delivery.failed"
FAILED_NAMESPACE = uuid.UUID("5b0c6f1e-7d1a-4c55-9a51-0d6f1d2c7e42")


def delivery_failed(order_id: int, reason: str) -> tuple[str, dict]:
    return DELIVERY_FAILED, {
        "event_id": str(uuid.uuid5(FAILED_NAMESPACE, f"delivery.failed:{order_id}")),
        "event_type": "DeliveryFailed",
        "occurred_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "order_id": order_id,
        "reason": reason,
    }


def free_couriers(db) -> int:
    """Курьеры на смене без активной доставки."""
    busy = select(DeliveryRow.courier_id).where(DeliveryRow.status == IN_PROGRESS,
                                                DeliveryRow.courier_id.is_not(None))
    return db.scalar(
        select(func.count()).select_from(CourierShiftRow)
        .where(CourierShiftRow.on_shift.is_(True), CourierShiftRow.courier_id.not_in(busy))
    )


class DeliveryPlanner:
    def __init__(self, session_factory: sessionmaker):
        self.session_factory = session_factory

    def __call__(self, routing_key: str, payload: dict) -> Outcome:
        order_id, event_id = payload["order_id"], payload["event_id"]
        with self.session_factory() as db:
            db.add(DeliveryProcessedEventRow(event_id=event_id))
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                request = db.get(DeliveryRequestRow, order_id)
                if request is not None and request.status == NO_COURIER:
                    return Outcome(f"Повтор event={short(event_id)}, заказ {order_id}: курьера не было, "
                                   f"повторяю delivery.failed",
                                   [delivery_failed(order_id, "Нет свободных курьеров")], event="duplicate_skipped")
                return Outcome(f"Повтор event={short(event_id)}, заказ {order_id} — уже обработано, пропускаю",
                               event="duplicate_skipped")

            free = free_couriers(db)
            db.add(DeliveryRequestRow(order_id=order_id, status=WAITING_COURIER if free else NO_COURIER,
                                      free_couriers=free))
            db.commit()

        if free:
            return Outcome(f"Подготовка доставки для заказа {order_id}: свободных курьеров {free} "
                           f"(event={short(event_id)})", event="delivery_planned")
        return Outcome(f"Заказ {order_id}: свободных курьеров нет → delivery.failed",
                       [delivery_failed(order_id, "Нет свободных курьеров")], event="delivery_failed")


async def main() -> None:
    observability.setup("delivery-worker")
    settings = DeliverySettings()
    session_factory = make_session_factory(settings.database_url)
    tracing.instrument_engine(session_factory.kw["bind"])
    planner = DeliveryPlanner(session_factory)
    await consume(settings.RABBITMQ_URL, DELIVERY, "Delivery", planner)


def run() -> None:
    asyncio.run(main())
