"""
Реализации OrderNotifier.

CeleryOrderNotifier — ставит задачи в очередь и сразу возвращает управление.
SyncOrderNotifier   — делает ту же работу прямо в запросе (замер «до»).
"""
import logging

from app.modules.orders.interfaces import OrderNotifier
from app.tasks import orders as tasks

logger = logging.getLogger(__name__)

# Если брокер недоступен, не ждать его долго: заказ уже оплачен и сохранён.
PUBLISH_RETRY = {"max_retries": 2, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.5}


class CeleryOrderNotifier(OrderNotifier):
    def order_created(self, order_id: int, email: str, phone: str | None) -> None:
        jobs = [(tasks.generate_order_pdf, (order_id,)), (tasks.send_order_email, (order_id, email))]
        if phone:
            jobs.append((tasks.send_order_sms, (order_id, phone)))
        for task, args in jobs:
            try:
                task.apply_async(args, retry=True, retry_policy=PUBLISH_RETRY)
            except Exception:
                # Заказ не откатываем: деньги списаны, еда готовится. Потерянное
                # уведомление — меньшее зло; оно видно в логах.
                logger.exception("Не удалось поставить %s для заказа %s", task.name, order_id)


class SyncOrderNotifier(OrderNotifier):
    def order_created(self, order_id: int, email: str, phone: str | None) -> None:
        try:
            tasks.make_receipt(order_id)
            tasks.send_email(order_id, email)
            if phone:
                tasks.send_sms(order_id, phone)
        except Exception:
            logger.exception("Ошибка обработки заказа %s", order_id)
