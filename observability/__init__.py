"""
Наблюдаемость: JSON-логи, correlation ID, трейсы OpenTelemetry, ошибки в Sentry,
метрики Prometheus.

Пакет общий, как messaging/: им пользуются и монолит, и сервис доставки.
Каждый процесс при старте вызывает setup("имя-сервиса").
"""
import os

from prometheus_client import start_http_server

from observability.errors import setup_sentry
from observability.logging import setup_logging
from observability.tracing import setup_tracing


def setup(service: str) -> None:
    """
    Логи включены всегда. Трейсы — если задан OTEL_EXPORTER_OTLP_ENDPOINT,
    Sentry — если задан SENTRY_DSN, отдельный порт метрик — если задан
    METRICS_PORT (у монолита метрики на /metrics его же HTTP-порта).
    """
    setup_logging(service)
    setup_tracing(service)
    setup_sentry(service)
    if port := os.environ.get("METRICS_PORT"):
        start_http_server(int(port))
