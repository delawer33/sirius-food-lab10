"""
Строка итога одной ступени для scripts/load_steps.sh: RPS и перцентили из
строки Aggregated Locust, средние CPU и соединений PostgreSQL (scripts/load_sampler.py).

    python3 scripts/load_summary.py <out> <users>
"""
import csv
import sys

out, users = sys.argv[1], sys.argv[2]
with open(f"{out}/u{users}_stats.csv") as f:
    row = next(r for r in csv.DictReader(f) if r["Name"] == "Aggregated")
with open(f"{out}/sample_{users}.txt") as f:
    # Первые 10 с — разгон пользователей (20 в секунду), в средние не берём.
    samples = [line.split() for line in f][5:]


def avg(i: int) -> float:
    values = [float(s[i]) for s in samples if len(s) > i and s[i] != "?"]
    return sum(values) / max(1, len(values))


fail = 100 * int(row["Failure Count"]) / max(1, int(row["Request Count"]))
print(f"{users:<6} {float(row['Requests/s']):8.1f} {row['50%']:>8} {row['95%']:>8} {row['99%']:>8} "
      f"{fail:8.2f} {avg(0):9.0f} {avg(1):9.0f} {avg(2):7.1f} {avg(3):7.1f} {avg(4):7.1f}")
