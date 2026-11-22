"""
Идемпотентность фоновых задач через Redis.

Ключ на пару «операция + заказ». SET NX атомарен: из двух одновременных
копий задачи начнёт работу только одна.

    running — задача выполняется сейчас (живёт RUNNING_TTL секунд: если
              воркер умер, ключ истечёт раньше, чем Celery вернёт задачу
              в очередь по visibility_timeout, и повтор выполнится);
    done    — уже сделано, повтор ничего не делает.
"""
from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum

from redis import Redis

RUNNING_TTL = 300
DONE_TTL = 86400


class Run(Enum):
    GO = "go"          # выполнять
    DONE = "done"      # уже выполнено раньше
    BUSY = "busy"      # прямо сейчас выполняет другой воркер


@contextmanager
def run_once(redis: Redis, key: str) -> Iterator[Run]:
    if not redis.set(key, "running", nx=True, ex=RUNNING_TTL):
        yield Run.DONE if redis.get(key) == "done" else Run.BUSY
        return
    try:
        yield Run.GO
    except BaseException:
        # Не получилось — снять отметку, чтобы ретрай выполнил работу заново.
        redis.delete(key)
        raise
    redis.set(key, "done", ex=DONE_TTL)
