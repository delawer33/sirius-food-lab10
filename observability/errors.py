"""
Ошибки в Sentry: стектрейс, запрос, теги service и correlation_id.

Включается переменной SENTRY_DSN. Подходит и sentry.io, и GlitchTip из
docker-compose (он принимает тот же протокол).
"""
import os

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from observability import correlation


def add_correlation_id(event, hint):
    """По тегу correlation_id ошибка в Sentry находится вместе с логами и трейсом."""
    if correlation_id := correlation.current():
        tags = event.setdefault("tags", {})
        if isinstance(tags, dict):
            tags.setdefault("correlation_id", correlation_id)
    return event


def setup_sentry(service: str) -> bool:
    dsn = os.environ.get("SENTRY_DSN")
    if not dsn:
        return False
    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "lab"),
        server_name=service,
        # Трейсы собирает OpenTelemetry, Sentry — только ошибки.
        traces_sample_rate=0,
        before_send=add_correlation_id,
        # Ошибки в логах остаются хлебными крошками, но отдельным issue не
        # становятся: исключение Sentry и так получает со стектрейсом.
        integrations=[LoggingIntegration(event_level=None)],
    )
    sentry_sdk.set_tag("service", service)
    return True
