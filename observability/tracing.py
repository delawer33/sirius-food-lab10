"""
OpenTelemetry: span'ы уходят в Jaeger по OTLP/HTTP.

Включается переменной OTEL_EXPORTER_OTLP_ENDPOINT (например http://jaeger:4318).
Без неё tracer — пустышка: span'ы не пишутся, inject ничего не добавляет.

Через RabbitMQ контекст трейса передаётся вручную, заголовком traceparent:
событие сначала лежит в outbox, и автоинструментация aio-pika привязала бы
публикацию к релею, а не к HTTP-запросу, который создал заказ.
"""
import os

from opentelemetry import propagate, trace
from opentelemetry.context import Context

tracer = trace.get_tracer("sirius")


def setup_tracing(service: str) -> bool:
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.grpc import GrpcInstrumentorClient, GrpcInstrumentorServer
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    # Адрес экспортёр берёт из OTEL_EXPORTER_OTLP_ENDPOINT и добавляет /v1/traces.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    # gRPC-вызовы монолита к сервису доставки — тоже span'ы, контекст в метаданных.
    GrpcInstrumentorClient().instrument()
    GrpcInstrumentorServer().instrument()
    return True


def enabled() -> bool:
    return not isinstance(trace.get_tracer_provider(), trace.ProxyTracerProvider)


def instrument_engine(engine) -> None:
    """SQL-запросы — span'ы внутри span'а запроса или обработки события."""
    if enabled():
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=engine)


def inject(carrier: dict) -> dict:
    """Кладёт traceparent текущего span'а в carrier (заголовки сообщения, outbox)."""
    propagate.inject(carrier)
    return carrier


def extract(carrier: dict | None) -> Context:
    """Контекст родительского span'а из заголовков. Значения bytes переводятся в str."""
    clean = {
        key: value.decode(errors="replace") if isinstance(value, bytes) else value
        for key, value in (carrier or {}).items()
        if isinstance(value, (str, bytes))
    }
    return propagate.extract(clean)
