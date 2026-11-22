"""
Логи — JSON-строки в stdout. Docker собирает stdout сам: docker logs sirius_app.

structlog и обычный logging (uvicorn, SQLAlchemy, aio-pika, свои logger'ы
проекта) выводятся одним форматтером, поэтому JSON — каждая строка.
Поля из contextvars (correlation_id, order_id, event_id) добавляются сами,
trace_id и span_id — из текущего span'а OpenTelemetry.
"""
import logging
import sys

import structlog
from opentelemetry import trace


def add_trace_ids(logger, method_name, event_dict):
    """По trace_id из лога трейс находится в Jaeger."""
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = format(context.trace_id, "032x")
        event_dict["span_id"] = format(context.span_id, "016x")
    return event_dict


def setup_logging(service: str, stream=None, level: int = logging.INFO) -> None:
    def add_service(logger, method_name, event_dict):
        event_dict.setdefault("service", service)
        return event_dict

    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_service,
        add_trace_ids,
    ]
    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[structlog.stdlib.add_logger_name, *shared],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.format_exc_info,
            # Имя события — в поле message, как в примере из методички.
            structlog.processors.EventRenamer("message"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
    )
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # uvicorn настраивает свои logger'ы сам, с текстовым форматом. Пусть пишут
    # через корневой. Строку на каждый запрос пишет наш middleware (с
    # correlation_id), access-лог uvicorn её бы дублировал.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    # aio-pika пишет INFO на каждое переподключение — оставляем предупреждения.
    logging.getLogger("aio_pika").setLevel(logging.WARNING)
    logging.getLogger("aiormq").setLevel(logging.WARNING)
