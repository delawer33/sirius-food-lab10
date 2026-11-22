"""
Кеш на Redis по стратегии Cache-Aside с защитой от cache stampede.

Знает только про ключи, строки и TTL. Что кешировать и когда сбрасывать,
решает репозиторий, который этим кешем пользуется.

Redis — ускоритель, а не источник данных: если он недоступен, значение
читается из БД, приложение работает медленнее, но работает.
"""
import logging
from collections.abc import Callable
from typing import TypeVar

from redis import Redis
from redis.exceptions import LockError, RedisError

from observability.metrics import CACHE_REQUESTS

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RedisCache:
    def __init__(self, redis: Redis, lock_timeout: float = 10.0, wait_timeout: float = 5.0):
        self.redis = redis
        # Сколько живёт блокировка, если её владелец упал, не отпустив её.
        self.lock_timeout = lock_timeout
        # Сколько остальные запросы ждут, пока первый заполнит кеш.
        self.wait_timeout = wait_timeout

    def get_or_load(
        self,
        key: str,
        ttl: int,
        loader: Callable[[], T],
        dump: Callable[[T], str],
        load: Callable[[str], T],
    ) -> T:
        """
        Cache-Aside: значение из кеша (hit), а при промахе (miss) — из loader
        с записью в кеш на ttl секунд.

        Защита от stampede: при промахе в БД идёт только запрос, взявший
        блокировку lock:{key}. Остальные ждут её освобождения и читают уже
        заполненный кеш. Блокировка в Redis, а не asyncio.Lock: она общая
        для всех процессов uvicorn и всех реплик приложения.
        """
        cached = self._get(key)
        if cached is not None:
            CACHE_REQUESTS.labels(result="hit").inc()
            return load(cached)
        CACHE_REQUESTS.labels(result="miss").inc()

        try:
            lock = self.redis.lock(
                f"lock:{key}",
                timeout=self.lock_timeout,
                blocking_timeout=self.wait_timeout,
                sleep=0.01,
            )
            acquired = lock.acquire()
        except RedisError:
            logger.warning("Redis недоступен, %s читается из БД", key)
            return loader()

        if not acquired:
            # Первый запрос слишком долго заполняет кеш. Ждать дальше хуже,
            # чем один лишний запрос в БД.
            logger.warning("Не дождались заполнения кеша %s", key)
            return loader()

        try:
            # Пока ждали блокировку, кеш мог заполнить другой запрос.
            cached = self._get(key)
            if cached is not None:
                return load(cached)
            value = loader()
            self._set(key, ttl, dump(value))
            return value
        finally:
            try:
                lock.release()
            except (LockError, RedisError):
                # Блокировка истекла сама или Redis пропал — её уже нет.
                pass

    def put(self, key: str, ttl: int, value: str) -> None:
        """Записать значение без чтения. Используется при прогреве кеша."""
        self._set(key, ttl, value)

    def delete(self, *keys: str) -> None:
        """Событийная инвалидация: данные изменились, кеш больше не верен."""
        try:
            self.redis.delete(*keys)
        except RedisError:
            # Удалить не вышло — устаревшее значение проживёт до конца TTL.
            logger.exception("Не удалось сбросить кеш %s", keys)

    def _get(self, key: str) -> str | None:
        try:
            return self.redis.get(key)
        except RedisError:
            logger.warning("Redis недоступен, кеш %s пропущен", key)
            return None

    def _set(self, key: str, ttl: int, value: str) -> None:
        try:
            self.redis.setex(key, ttl, value)
        except RedisError:
            logger.warning("Redis недоступен, %s не закеширован", key)
