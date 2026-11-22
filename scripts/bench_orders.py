"""
Время ответа POST /orders/create: N заказов подряд от демо-студента.

    python -m scripts.bench_orders sync   --host http://127.0.0.1:8000
    python -m scripts.bench_orders celery --host http://127.0.0.1:8000

Нужны демо-данные (scripts.seed_demo). Перед замером администратор пополняет
баланс студента. Сервер запускать с RATE_LIMIT_ENABLED=False: лимит — 10
заказов в минуту. Результат: docs/bench_orders/<label>.json.
"""
import argparse
import json
import statistics
import time
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "docs" / "bench_orders"
PASSWORD = "sirius-demo"


def login(client: httpx.Client, email: str) -> dict:
    response = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("label")
    parser.add_argument("--host", default="http://127.0.0.1:8000")
    parser.add_argument("-n", type=int, default=10)
    parser.add_argument("--item-id", type=int, default=2, help="Компот из seed_demo")
    args = parser.parse_args()

    with httpx.Client(base_url=args.host, timeout=60) as client:
        student, admin = login(client, "student@sirius.ru"), login(client, "admin@sirius.ru")
        me = client.get("/users/me", headers=student).json()
        client.post(f"/users/{me['id']}/topup", params={"amount": 10000}, headers=admin).raise_for_status()

        times, order_ids = [], []
        for _ in range(args.n):
            started = time.perf_counter()
            response = client.post("/orders/create", json={"item_id": args.item_id, "quantity": 1},
                                   headers=student)
            times.append((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            order_ids.append(response.json()["order_id"])

    summary = {
        "label": args.label,
        "requests": args.n,
        "order_ids": order_ids,
        "avg_ms": round(statistics.mean(times), 1),
        "median_ms": round(statistics.median(times), 1),
        "max_ms": round(max(times), 1),
        "min_ms": round(min(times), 1),
        "times_ms": [round(t, 1) for t in times],
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.label}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "times_ms"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
