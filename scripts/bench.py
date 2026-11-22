"""
Один замер нагрузки на GET /menu/items: Locust без веб-интерфейса плюс
счётчики PostgreSQL и load average.

    python -m scripts.bench before --host http://127.0.0.1:8000
    python -m scripts.bench after  --host http://127.0.0.1:8000

Приложение должно быть уже запущено (для «before» — с CACHE_ENABLED=False).
Результаты: docs/bench/<label>_stats.csv, _stats_history.csv, <label>.html
и сводка <label>.json. Графики «до/после» — scripts/plot_bench.py.
"""
import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from sqlalchemy import create_engine, text

from app.core.config import settings

OUT = Path(__file__).resolve().parent.parent / "docs" / "bench"

PG_STATS = text(
    "SELECT xact_commit + xact_rollback, tup_returned "
    "FROM pg_stat_database WHERE datname = current_database()"
)


def pg_counters() -> tuple[int, int]:
    engine = create_engine(settings.DATABASE_URL)
    with engine.connect() as conn:
        transactions, rows = conn.execute(PG_STATS).one()
    engine.dispose()
    return transactions, rows


def pg_cpu_seconds(container: str) -> float | None:
    """Процессорное время контейнера PostgreSQL из его cgroup (cgroup v2)."""
    try:
        stat = subprocess.run(
            ["docker", "exec", container, "cat", "/sys/fs/cgroup/cpu.stat"],
            capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    usage = next(line for line in stat.splitlines() if line.startswith("usage_usec"))
    return int(usage.split()[1]) / 1_000_000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("label")
    parser.add_argument("--host", default="http://127.0.0.1:8000")
    parser.add_argument("--users", type=int, default=500)
    parser.add_argument("--spawn-rate", type=int, default=10)
    parser.add_argument("--run-time", default="90s")
    parser.add_argument("--db-container", default="sirius-food-lab4-db-1")
    parser.add_argument("--note", default="", help="как запущено приложение")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    prefix = OUT / args.label
    tx_before, rows_before = pg_counters()
    cpu_before = pg_cpu_seconds(args.db_container)
    started = time.time()
    subprocess.run(
        [
            sys.executable, "-m", "locust", "-f", "locustfile.py", "--headless",
            "--host", args.host, "-u", str(args.users), "-r", str(args.spawn_rate),
            "--run-time", args.run_time, "--csv", str(prefix), "--html", f"{prefix}.html",
            "--only-summary",
        ],
        check=False,
    )
    elapsed = time.time() - started
    load1, load5, _ = os.getloadavg()
    tx_after, rows_after = pg_counters()
    cpu_after = pg_cpu_seconds(args.db_container)

    with open(f"{prefix}_stats.csv", encoding="utf-8") as f:
        total = next(row for row in csv.DictReader(f) if row["Name"] == "Aggregated")

    summary = {
        "label": args.label,
        "note": args.note,
        "users": args.users,
        "requests": int(total["Request Count"]),
        "failures": int(total["Failure Count"]),
        "rps": round(float(total["Requests/s"]), 1),
        "avg_ms": round(float(total["Average Response Time"]), 1),
        "median_ms": float(total["50%"]),
        "p95_ms": float(total["95%"]),
        "p99_ms": float(total["99%"]),
        "pg_transactions": tx_after - tx_before,
        "pg_rows_read": rows_after - rows_before,
        "pg_cpu_seconds": (
            round(cpu_after - cpu_before, 1) if cpu_before is not None and cpu_after is not None else None
        ),
        "load_avg_1m": round(load1, 2),
        "load_avg_5m": round(load5, 2),
        "seconds": round(elapsed),
    }
    Path(f"{prefix}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
