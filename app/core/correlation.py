"""
Middleware для correlation_id.

Берёт X-Correlation-ID из запроса или генерирует новый, кладёт в
request.state и в contextvars логов, возвращает клиенту в заголовке ответа.
Здесь же пишется одна строка лога на запрос: метод, путь, статус, время.
"""
import time

import sentry_sdk
import structlog
from fastapi import Request
from fastapi.responses import PlainTextResponse
from opentelemetry import trace

from observability import correlation

logger = structlog.get_logger()

# Prometheus опрашивает /metrics каждые 5 с: строка лога на каждый опрос — шум.
QUIET_PATHS = ("/metrics",)


async def correlation_id_middleware(request: Request, call_next):
    correlation_id = correlation.accept(request.headers.get(correlation.HEADER))
    # Доступен в эндпоинтах как request.state.correlation_id.
    request.state.correlation_id = correlation_id
    # Все логи этого запроса, включая синхронные обработчики в пуле потоков,
    # получат поле correlation_id: contextvars копируются в поток.
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)
    # По тегу трейс ищется в Jaeger, ошибка — в Sentry.
    trace.get_current_span().set_attribute("correlation_id", correlation_id)
    sentry_sdk.set_tag("correlation_id", correlation_id)

    started = time.perf_counter()
    fields = {"method": request.method, "path": request.url.path}
    try:
        response = await call_next(request)
    except Exception as error:
        logger.exception("request_failed", **fields, status=500, duration_ms=_ms(started))
        # Ответ 500 собираем здесь, чтобы и в нём был X-Correlation-ID: по нему
        # клиент или поддержка найдут ошибку в логах и в Sentry.
        sentry_sdk.capture_exception(error)
        return PlainTextResponse(
            "Internal Server Error", status_code=500, headers={correlation.HEADER: correlation_id}
        )
    response.headers[correlation.HEADER] = correlation_id
    if request.url.path not in QUIET_PATHS:
        logger.info("http_request", **fields, status=response.status_code, duration_ms=_ms(started))
    return response


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
