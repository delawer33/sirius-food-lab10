"""
Время ответа GET /menu/items без нагрузки: N последовательных запросов
одним клиентом. Показывает цену одного запроса без очереди.

    python -m scripts.bench_latency nocache --host http://127.0.0.1:8000
"""
import argparse
import json
import statistics
import time
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "docs" / "bench"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("label")
    parser.add_argument("--host", default="http://127.0.0.1:8000")
    parser.add_argument("-n", type=int, default=200)
    args = parser.parse_args()

    times = []
    with httpx.Client(base_url=args.host) as client:
        client.get("/menu/items")  # прогрев соединения
        for _ in range(args.n):
            started = time.perf_counter()
            client.get("/menu/items").raise_for_status()
            times.append((time.perf_counter() - started) * 1000)
    times.sort()
    summary = {
        "label": args.label,
        "requests": args.n,
        "median_ms": round(statistics.median(times), 2),
        "p95_ms": round(times[int(len(times) * 0.95) - 1], 2),
        "min_ms": round(times[0], 2),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"latency_{args.label}.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
