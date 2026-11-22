"""
Фоновые задачи заказа: чек в PDF, письмо и SMS.

Реальных PDF-генератора, почты и SMS-шлюза в проекте нет: работа
имитируется задержкой (PDF_DELAY и т. д.), чек пишется текстовым файлом.
Функции make_receipt, send_email, send_sms — сама работа; задачи Celery
добавляют к ней ретраи, идемпотентность и DLQ. Синхронный режим
(NOTIFICATIONS_MODE=sync) вызывает те же функции прямо в запросе.
"""
import logging
import time
from pathlib import Path

from app.core.celery_app import celery_app
from app.core.config import settings
from app.core.redis import redis_client
from app.tasks.base import LoggedTask
from app.tasks.idempotency import Run, run_once

logger = logging.getLogger(__name__)


class ExternalServiceError(Exception):
    """Внешний сервис (почта, SMS-шлюз) временно недоступен."""


def make_receipt(order_id: int) -> str:
    time.sleep(settings.PDF_DELAY)
    folder = Path(settings.RECEIPTS_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"order_{order_id}.pdf.txt"
    path.write_text(f"Сириус.Еда\nЧек по заказу № {order_id}\n", encoding="utf-8")
    return str(path)


def send_email(order_id: int, email: str) -> None:
    time.sleep(settings.EMAIL_DELAY)
    if settings.EMAIL_FAIL_EVERY and order_id % settings.EMAIL_FAIL_EVERY == 0:
        raise ExternalServiceError("Email service unavailable")


def send_sms(order_id: int, phone: str) -> None:
    time.sleep(settings.SMS_DELAY)


# Общие настройки ретраев: при любой ошибке повторить до 3 раз с
# экспоненциальной задержкой 1, 2, 4 с (со случайным разбросом, чтобы
# повторы от разных задач не били во внешний сервис одновременно).
RETRY = dict(
    base=LoggedTask,
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=1,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)


def _once(task, key: str, work) -> str:
    with run_once(redis_client, key) as state:
        if state is Run.DONE:
            logger.info("%s: уже выполнено, пропуск (%s)", task.name, key)
            return f"SKIP already done: {key}"
        if state is Run.BUSY:
            logger.info("%s: выполняется другим воркером, пропуск (%s)", task.name, key)
            return f"SKIP in progress: {key}"
        return work()


@celery_app.task(**RETRY)
def generate_order_pdf(self, order_id: int) -> str:
    """Генерация чека. Повторный запуск не создаёт второй чек."""
    return _once(self, f"pdf_generated:{order_id}",
                 lambda: f"PDF generated for order {order_id}: {make_receipt(order_id)}")


@celery_app.task(**RETRY)
def send_order_email(self, order_id: int, email: str) -> str:
    """Письмо о заказе. Повторный запуск не отправляет второе письмо."""
    def work():
        send_email(order_id, email)
        return f"Email sent to {email} for order {order_id}"

    return _once(self, f"email_sent:{order_id}", work)


@celery_app.task(**RETRY)
def send_order_sms(self, order_id: int, phone: str) -> str:
    """SMS о заказе. Повторный запуск не отправляет второе SMS."""
    def work():
        send_sms(order_id, phone)
        return f"SMS sent to {phone} for order {order_id}"

    return _once(self, f"sms_sent:{order_id}", work)
