"""
Correlation ID — один идентификатор на всю бизнес-операцию: HTTP-запрос,
события в RabbitMQ, обработку в consumer'ах.

Текущий ID лежит в contextvars structlog. Всё, что залогировано в этом
контексте, получает поле correlation_id само; publisher кладёт его в
заголовок сообщения, outbox — в свою строку.
"""
import re
import uuid

import structlog

HEADER = "X-Correlation-ID"
# Чужой ID попадает в логи и заголовки: берём только то, что похоже на ID.
_VALID = re.compile(r"[A-Za-z0-9._:-]{1,128}")


def accept(value: str | bytes | None) -> str:
    """ID от клиента или из сообщения, если он корректен, иначе новый."""
    if isinstance(value, bytes):
        value = value.decode(errors="replace")
    if value and _VALID.fullmatch(value):
        return value
    return str(uuid.uuid4())


def current() -> str | None:
    return structlog.contextvars.get_contextvars().get("correlation_id")
