"""
Приложение Celery: брокер и хранилище результатов — Redis.

    celery -A app.core.celery_app worker --loglevel=info   # воркер
    celery -A app.core.celery_app beat --loglevel=info     # периодические задачи
    celery -A app.core.celery_app flower                   # мониторинг, :5555
"""
from celery import Celery
from celery.schedules import crontab
from kombu import Exchange, Queue

from app.core.config import settings

celery_app = Celery(
    "sirius_food",
    broker=settings.broker_url,
    backend=settings.broker_url,
    include=["app.tasks.orders", "app.tasks.maintenance"],
)

celery_app.conf.update(
    # JSON вместо pickle: из очереди нельзя подсунуть произвольный объект.
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Подтверждать задачу после выполнения, а не при получении: если воркер
    # упадёт посреди задачи, она вернётся в очередь и выполнится другим.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Не брать задачи впрок: долгая задача не задерживает соседние.
    worker_prefetch_multiplier=1,
    # Через сколько неподтверждённая задача снова станет видна воркерам.
    broker_transport_options={"visibility_timeout": 3600},
    result_expires=86400,
    # Нужно Flower: показывать задачи сразу после постановки, а не только запуска.
    task_track_started=True,
    task_send_sent_event=True,
    worker_send_task_events=True,
    broker_connection_retry_on_startup=True,
)

# Одна рабочая очередь. «Мёртвые» задачи (исчерпали ретраи) кладутся не в
# очередь Celery, а в Redis-список dlq: их никто не должен забирать
# автоматически, их разбирают руками (scripts/dlq.py).
celery_app.conf.task_queues = (Queue("default", Exchange("default"), routing_key="default"),)
celery_app.conf.task_default_queue = "default"
celery_app.conf.task_default_exchange = "default"
celery_app.conf.task_default_routing_key = "default"

celery_app.conf.beat_schedule = {
    "update-order-stats-every-minute": {
        "task": "app.tasks.maintenance.update_order_stats",
        "schedule": 60.0,
    },
    "cleanup-task-logs-daily": {
        "task": "app.tasks.maintenance.cleanup_task_logs",
        "schedule": crontab(hour=3, minute=0),
    },
}
