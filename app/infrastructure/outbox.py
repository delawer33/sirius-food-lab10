"""
Запись доменных событий в outbox. Вызывается репозиториями до commit, поэтому
событие сохраняется в той же транзакции, что и изменение данных: либо есть
и заказ, и событие, либо нет ничего.

Вместе с событием сохраняются correlation_id и traceparent текущего запроса:
релей опубликует событие позже, из другого процесса, и возьмёт их отсюда.
"""
import json
from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.domain.events import DomainEvent
from app.models import OutboxEvent
from observability import correlation, tracing


def add_to_outbox(db: Session, events: Iterable[DomainEvent]) -> None:
    correlation_id = correlation.current()
    trace_context = tracing.inject({})
    db.add_all(
        OutboxEvent(
            event_id=event.event_id,
            routing_key=event.routing_key,
            payload=json.dumps(event.payload, ensure_ascii=False),
            correlation_id=correlation_id,
            trace_context=json.dumps(trace_context) if trace_context else None,
        )
        for event in events
    )
