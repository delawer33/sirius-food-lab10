"""
Свои метрики проекта. HTTP-метрики монолита (RED) пишет
prometheus-fastapi-instrumentator, здесь — то, чего он не знает.

Метки только с короткими фиксированными наборами значений: queue, result,
routing_key. order_id или correlation_id в метке завели бы по временному
ряду на каждый заказ (высокая кардинальность), им место в логах.
"""
from prometheus_client import Counter, Gauge, Histogram

ORDERS_CREATED = Counter("sirius_orders_created_total", "Оформленные заказы")
CACHE_REQUESTS = Counter("sirius_cache_requests_total", "Чтения кеша меню", ["result"])

EVENTS_CONSUMED = Counter(
    "sirius_events_consumed_total", "Сообщения, обработанные consumer'ом", ["queue", "result"]
)
EVENT_DURATION = Histogram(
    "sirius_event_processing_seconds", "Время обработки сообщения consumer'ом", ["queue"]
)
EVENTS_PUBLISHED = Counter("sirius_events_published_total", "Опубликованные события", ["routing_key"])
OUTBOX_PENDING = Gauge("sirius_outbox_pending", "События в outbox, ещё не отправленные в RabbitMQ")
