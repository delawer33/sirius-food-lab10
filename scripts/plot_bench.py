"""
Графики «до/после» по результатам scripts/bench.py.

    python -m scripts.plot_bench before_1w after_1w --out docs/bench/1w
    python -m scripts.plot_bench before_4w after_4w --out docs/bench/4w

Строит <out>_rps.png (запросов в секунду по ходу теста) и <out>_latency.png
(95-й перцентиль времени ответа), а также печатает таблицу для README.
"""
import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

BENCH = Path(__file__).resolve().parent.parent / "docs" / "bench"
COLORS = {"до": "#c0392b", "после": "#2471a3"}


def history(label: str) -> tuple[list[float], list[float], list[float]]:
    seconds, rps, p95 = [], [], []
    with open(BENCH / f"{label}_stats_history.csv", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["Name"] == "Aggregated"]
    start = int(rows[0]["Timestamp"])
    for row in rows:
        if row["95%"] in ("N/A", ""):
            continue
        seconds.append(int(row["Timestamp"]) - start)
        rps.append(float(row["Requests/s"]))
        p95.append(float(row["95%"]))
    return seconds, rps, p95


def plot(labels: dict[str, str], metric: int, ylabel: str, title: str, path: Path, log=False):
    fig, ax = plt.subplots(figsize=(8, 4))
    for kind, label in labels.items():
        data = history(label)
        ax.plot(data[0], data[metric], label=f"{kind}: {label}", color=COLORS[kind], linewidth=2)
    ax.set_xlabel("секунды с начала теста (500 пользователей, +10 в секунду)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    if log:
        ax.set_yscale("log")
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    labels = {"до": args.before, "после": args.after}

    plot(labels, 1, "запросов в секунду", "GET /menu/items: RPS", Path(f"{args.out}_rps.png"))
    plot(
        labels, 2, "мс (логарифмическая шкала)", "GET /menu/items: 95-й перцентиль",
        Path(f"{args.out}_latency.png"), log=True,
    )

    b, a = (json.loads((BENCH / f"{label}.json").read_text()) for label in labels.values())
    rows = [
        ("Запросов за 90 с", "requests"), ("Ошибок", "failures"), ("RPS", "rps"),
        ("Среднее время, мс", "avg_ms"), ("Медиана, мс", "median_ms"),
        ("95-й перцентиль, мс", "p95_ms"), ("99-й перцентиль, мс", "p99_ms"),
        ("Транзакций в PostgreSQL", "pg_transactions"), ("Строк прочитано PostgreSQL", "pg_rows_read"),
        ("CPU PostgreSQL, с", "pg_cpu_seconds"), ("Load average (1 мин)", "load_avg_1m"),
    ]
    print(f"| Метрика | До ({b['note']}) | После ({a['note']}) |")
    print("|---|---|---|")
    for title, key in rows:
        print(f"| {title} | {b[key]} | {a[key]} |")


if __name__ == "__main__":
    main()
