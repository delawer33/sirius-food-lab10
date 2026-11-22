"""
Consumer кухни. order.paid — заказ встаёт в очередь кухни, order.cancelled —
снимается с готовки.

    python -m app.workers.kitchen_consumer

Идемпотентность: event_id записывается в processed_events в одной
транзакции с изменением kitchen_orders. Первичный ключ (consumer, event_id)
не даст записать событие второй раз даже двум процессам одновременно.
"""
import asyncio

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
import observability
from app.database import SessionLocal, engine
from app.domain.events import ORDER_CANCELLED, ORDER_PAID
from app.models import KitchenOrder, ProcessedEvent
from messaging.consumer import Outcome, consume, short
from messaging.topology import KITCHEN
from observability import tracing

CONSUMER = "kitchen"


class KitchenHandler:
    def __init__(self, session_factory: sessionmaker = SessionLocal):
        self.session_factory = session_factory

    def __call__(self, routing_key: str, payload: dict) -> Outcome:
        order_id, event_id = payload["order_id"], payload["event_id"]
        with self.session_factory() as db:
            db.add(ProcessedEvent(consumer=CONSUMER, event_id=event_id))
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                return Outcome(f"Повтор event={short(event_id)} ({routing_key}, заказ {order_id}) — уже обработано, пропускаю",
                               event="duplicate_skipped")

            if routing_key == ORDER_PAID:
                db.add(KitchenOrder(order_id=order_id, status="pending"))
                text, event = f"Принят заказ {order_id} (event={short(event_id)})", "order_received"
            elif routing_key == ORDER_CANCELLED:
                row = db.query(KitchenOrder).filter_by(order_id=order_id).first()
                if row is not None:
                    row.status = "cancelled"
                text = f"Заказ {order_id} снят с готовки: {payload.get('reason', '')} (event={short(event_id)})"
                event = "kitchen_order_cancelled"
            else:
                text, event = f"Событие {routing_key} кухне не нужно, пропускаю", "event_ignored"
            db.commit()
        return Outcome(text, event=event)


async def main() -> None:
    observability.setup("kitchen")
    tracing.instrument_engine(engine)
    await consume(settings.RABBITMQ_URL, KITCHEN, "Kitchen", KitchenHandler())


if __name__ == "__main__":
    asyncio.run(main())
