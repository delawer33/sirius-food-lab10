"""
Ограничение частоты запросов на Redis (фиксированное окно).

Счётчик лежит в Redis, а не в памяти процесса: при нескольких репликах
приложения у каждой был бы свой счётчик, и лимит умножался бы на их число.
"""
import logging

from fastapi import Depends, HTTPException, Request
from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.redis import get_redis

logger = logging.getLogger(__name__)


def rate_limit(max_requests: int = 5, window: int = 60, scope: str | None = None):
    """
    Dependency: не больше max_requests запросов с одного IP за window секунд.
    Счётчик общий для всех эндпоинтов с одинаковым scope (по умолчанию — путь),
    так у /auth/login и /auth/token один лимит на двоих.
    Возбуждает HTTPException 429 при превышении лимита.
    """

    def checker(request: Request, redis: Redis = Depends(get_redis)) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        ip = request.client.host if request.client else "unknown"
        key = f"rate_limit:{scope or request.url.path}:{ip}"
        try:
            # SET NX EX создаёт счётчик сразу со сроком жизни. В варианте
            # «INCR, потом EXPIRE» падение между командами оставило бы ключ
            # без срока, и IP остался бы заблокированным навсегда.
            pipe = redis.pipeline()
            pipe.set(key, 0, ex=window, nx=True)
            pipe.incr(key)
            pipe.ttl(key)
            _, current, ttl = pipe.execute()
        except RedisError:
            # Secure by Default: без Redis нельзя посчитать попытки входа,
            # поэтому запрос отклоняется, а не пропускается без лимита.
            logger.exception("Redis недоступен, rate limiting не работает")
            raise HTTPException(status_code=503, detail="Сервис временно недоступен")
        if current > max_requests:
            raise HTTPException(
                status_code=429,
                detail="Слишком много запросов, попробуйте позже",
                headers={"Retry-After": str(max(ttl, 1))},
            )

    return checker
