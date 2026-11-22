"""
RedisCache: Cache-Aside, TTL, работа без Redis и защита от cache stampede.
"""
import threading
import time

from redis.exceptions import ConnectionError as RedisConnectionError

from app.infrastructure.cache import RedisCache


class Loader:
    """Источник данных вместо БД: считает, сколько раз к нему пришли."""

    def __init__(self, value="from-db", delay=0.0):
        self.value = value
        self.delay = delay
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self):
        with self._lock:
            self.calls += 1
        time.sleep(self.delay)
        return self.value


def get(cache, loader, key="k", ttl=300):
    return cache.get_or_load(key, ttl, loader, dump=str, load=str)


def test_miss_loads_and_caches_with_ttl(redis):
    cache, loader = RedisCache(redis), Loader()

    assert get(cache, loader) == "from-db"

    assert loader.calls == 1
    assert redis.get("k") == "from-db"
    assert 290 < redis.ttl("k") <= 300


def test_hit_does_not_touch_db(redis):
    cache, loader = RedisCache(redis), Loader()
    redis.setex("k", 300, "from-cache")

    assert get(cache, loader) == "from-cache"
    assert loader.calls == 0


def test_expired_key_goes_to_db_again(redis):
    cache, loader = RedisCache(redis), Loader()
    get(cache, loader, ttl=1)
    redis.delete("k")  # так выглядит ключ после истечения TTL

    get(cache, loader)

    assert loader.calls == 2


def test_delete_invalidates(redis):
    cache, loader = RedisCache(redis), Loader()
    get(cache, loader)

    cache.delete("k")

    assert redis.exists("k") == 0
    get(cache, loader)
    assert loader.calls == 2


class DownRedis:
    """Redis, до которого не достучаться."""

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise RedisConnectionError("redis is down")

        return fail


def test_redis_down_falls_back_to_db():
    """Кеш — ускоритель, а не источник данных: без Redis всё работает, только медленнее."""
    cache, loader = RedisCache(DownRedis()), Loader()

    assert [get(cache, loader) for _ in range(3)] == ["from-db"] * 3
    assert loader.calls == 3
    cache.delete("k")  # не падает


def test_stampede_only_one_request_goes_to_db(redis):
    """50 одновременных промахов: в БД идёт один запрос, остальные дожидаются кеша."""
    cache, loader = RedisCache(redis), Loader(delay=0.2)
    barrier = threading.Barrier(50)
    results = []

    def request():
        barrier.wait()
        results.append(get(cache, loader))

    threads = [threading.Thread(target=request) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == ["from-db"] * 50
    assert loader.calls == 1
    assert redis.exists("lock:k") == 0  # блокировка отпущена


def test_waiter_gives_up_and_reads_db(redis):
    """Если владелец блокировки завис, ожидающий не висит вечно, а идёт в БД."""
    cache, loader = RedisCache(redis, wait_timeout=0.1), Loader()
    redis.set("lock:k", "someone-else", px=5000)

    started = time.monotonic()
    assert get(cache, loader) == "from-db"

    assert time.monotonic() - started < 1
    assert loader.calls == 1
