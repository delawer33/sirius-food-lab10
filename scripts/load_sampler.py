"""
Замер ресурсов во время нагрузки, для scripts/load_steps.sh. Раз в 2 с печатает:

    cpu_api cpu_locust pg_active pg_idle_in_tx pg_total

cpu — %CPU за последние 2 с (100 = одно ядро целиком), сумма по процессам
uvicorn (с воркерами) и Locust. pg_* — соединения приложения в PostgreSQL:
выполняют запрос / держат открытую транзакцию / всего.

    python -m scripts.load_sampler postgresql://sirius:sirius@127.0.0.1:5442/sirius_food
"""
import sys
import time

import psutil
import psycopg2

PG_QUERY = """
    SELECT count(*) FILTER (WHERE state = 'active'),
           count(*) FILTER (WHERE state = 'idle in transaction'),
           count(*)
    FROM pg_stat_activity
    WHERE datname = current_database() AND pid <> pg_backend_pid()
"""


def find(*needles: str) -> list[psutil.Process]:
    found = []
    for proc in psutil.process_iter(["cmdline"]):
        cmdline = " ".join(proc.info["cmdline"] or [])
        if all(n in cmdline for n in needles):
            found.append(proc)
            found.extend(proc.children(recursive=True))
    return found


def cpu(procs: list[psutil.Process]) -> float:
    total = 0.0
    for proc in procs:
        try:
            total += proc.cpu_percent(None)
        except psutil.Error:
            pass
    return total


def main() -> None:
    conn = psycopg2.connect(sys.argv[1])
    conn.autocommit = True
    api, loc = find("uvicorn", "app.main:app"), find("locust", "-f")
    cpu(api), cpu(loc)  # первый вызов cpu_percent только запоминает точку отсчёта
    while True:
        time.sleep(2)
        if not loc:
            loc = find("locust", "-f")
        with conn.cursor() as cur:
            cur.execute(PG_QUERY)
            active, idle_tx, total = cur.fetchone()
        print(f"{cpu(api):.0f} {cpu(loc):.0f} {active} {idle_tx} {total}", flush=True)


if __name__ == "__main__":
    main()
