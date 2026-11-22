"""
Клиент Redis. Общий для кеша меню и rate limiting.

decode_responses=True: из Redis приходят строки, а не байты — удобно для JSON.
socket_timeout: если Redis завис, запрос не ждёт его дольше секунды, а идёт
в БД (кеш) или отвечает 503 (rate limit).
"""
import redis
from redis import Redis

from app.core.config import settings

redis_client: Redis = redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_timeout=1,
    socket_connect_timeout=1,
)


def get_redis() -> Redis:
    """Клиент Redis. В тестах подменяется на fakeredis через dependency_overrides."""
    return redis_client


def check_redis_connection() -> bool:
    """Проверка соединения с Redis."""
    try:
        return redis_client.ping()
    except redis.RedisError:
        return False
