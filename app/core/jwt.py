"""
Создание и проверка JWT.

Payload только подписан, но не зашифрован, поэтому в нём нет ничего,
кроме идентификатора пользователя и служебных полей.
"""
import uuid
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"
ACCESS = "access"
REFRESH = "refresh"


class InvalidTokenError(Exception):
    """Подпись не сошлась, срок истёк, payload повреждён или тип не тот."""


def _encode(user_id: int, token_version: int, token_type: str, lifetime: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "ver": token_version,
        "iat": now,
        "exp": now + lifetime,
        # Уникальный id: два токена, выданные в одну секунду, всё равно различаются.
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def create_access_token(user_id: int, token_version: int = 0) -> str:
    """Создаёт короткоживущий access-токен (15 минут)."""
    lifetime = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return _encode(user_id, token_version, ACCESS, lifetime)


def create_refresh_token(user_id: int, token_version: int = 0) -> str:
    """Создаёт долгоживущий refresh-токен (7 дней)."""
    lifetime = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return _encode(user_id, token_version, REFRESH, lifetime)


def decode_token(token: str, expected_type: str) -> dict:
    """
    Проверяет подпись, срок и тип токена и возвращает payload.
    Refresh-токен нельзя предъявить вместо access и наоборот.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        int(payload["sub"])
        int(payload["ver"])
    except (JWTError, KeyError, TypeError, ValueError) as error:
        raise InvalidTokenError() from error
    if payload.get("type") != expected_type:
        raise InvalidTokenError()
    return payload


def expires_at(token: str) -> datetime:
    """
    Момент истечения только что выданного токена (UTC, без tzinfo — так он
    хранится в БД). Подпись не проверяется: токен создан здесь же.
    """
    exp = jwt.get_unverified_claims(token)["exp"]
    return datetime.fromtimestamp(exp, tz=timezone.utc).replace(tzinfo=None)
