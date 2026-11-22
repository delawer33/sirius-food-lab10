"""
Трансляция доменных исключений в HTTP-ответы. Используется роутерами.
"""
from fastapi import HTTPException

from app.domain.errors import (
    AccessDeniedError,
    AuthenticationError,
    DomainError,
    NotFoundError,
    ServiceTimeoutError,
    ServiceUnavailableError,
)

_STATUS_BY_ERROR = {
    NotFoundError: 404,
    AccessDeniedError: 403,
    AuthenticationError: 401,
    ServiceUnavailableError: 503,
    ServiceTimeoutError: 504,
}


def to_http_exception(error: DomainError) -> HTTPException:
    """404, 403, 401; 503 — сервис доставки недоступен, 504 — не ответил; 400 остальное."""
    status_code = _STATUS_BY_ERROR.get(type(error), 400)
    # RFC 6750: ответ 401 сообщает клиенту схему аутентификации.
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return HTTPException(status_code=status_code, detail=error.message, headers=headers)
