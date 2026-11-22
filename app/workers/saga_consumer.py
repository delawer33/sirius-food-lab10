"""
Участник саги со стороны заказов. Слушает delivery.failed от сервиса доставки
и выполняет компенсацию: отменяет заказ, возвращает деньги, публикует
order.cancelled (через outbox).

    python -m app.workers.saga_consumer

Идемпотентность — по ключу компенсации: в refunds не бывает двух строк на
один заказ, а уже отменённый заказ сервис не трогает.
"""
import asyncio

from sqlalchemy.orm import sessionmaker

from app.core.config import settings
import observability
from app.database import SessionLocal, engine
from app.modules.orders.repository import SqlAlchemyOrderRepository
from app.modules.orders.service import OrderService
from messaging.consumer import Outcome, consume, short
from messaging.topology import SAGA
from observability import tracing


class SagaHandler:
    def __init__(self, session_factory: sessionmaker = SessionLocal):
        self.session_factory = session_factory

    def __call__(self, routing_key: str, payload: dict) -> Outcome:
        order_id, event_id = payload["order_id"], payload["event_id"]
        with self.session_factory() as db:
            # Уведомления при компенсации не нужны.
            service = OrderService(SqlAlchemyOrderRepository(db), notifier=None)
            order = service.compensate_failed_delivery(order_id)
        if order is None:
            return Outcome(f"Повтор event={short(event_id)}: заказ {order_id} уже отменён, компенсация не нужна",
                           event="duplicate_skipped")
        return Outcome(
            f"Компенсация заказа {order_id}: причина «{payload.get('reason', '?')}» → "
            f"заказ cancelled, клиенту {order.user_id} возвращено {order.total_cost:g} ₽, "
            f"order.cancelled записан в outbox",
            event="order_compensated",
        )


async def main() -> None:
    observability.setup("saga")
    tracing.instrument_engine(engine)
    await consume(settings.RABBITMQ_URL, SAGA, "Saga", SagaHandler())


if __name__ == "__main__":
    asyncio.run(main())
