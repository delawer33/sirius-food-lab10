#!/usr/bin/env bash
# Нагрузка ступенями без веб-интерфейса: на каждой ступени Locust держит N
# пользователей DURATION секунд. Параллельно scripts/load_sampler.py снимает
# CPU uvicorn и Locust и соединения приложения в PostgreSQL.
#
#   ./scripts/load_steps.sh docs/lab10/load/1worker 50 100 200 400
#
# Итог по ступеням — в <out>/summary.txt, CSV Locust и замеры — рядом.
set -eu
cd "$(dirname "$0")/.."
OUT="$1"; shift
DURATION="${DURATION:-60}"
HOST="${HOST:-http://127.0.0.1:8010}"
LOCUST="${LOCUST:-.venv/bin/locust}"
mkdir -p "$OUT"

PG_URL="${PG_URL:-postgresql://sirius:sirius@127.0.0.1:5442/sirius_food}"

printf "%-6s %8s %8s %8s %8s %8s %9s %9s %7s %7s %7s\n" \
  users rps p50_ms p95_ms p99_ms fail% cpu_api% cpu_loc% pg_act pg_idtx pg_all > "$OUT/summary.txt"
for USERS in "$@"; do
  .venv/bin/python -m scripts.load_sampler "$PG_URL" > "$OUT/sample_$USERS.txt" &
  SAMPLER=$!
  "$LOCUST" -f locustfile.py --host "$HOST" --headless -u "$USERS" -r 20 -t "${DURATION}s" \
    --csv "$OUT/u$USERS" --only-summary > "$OUT/locust_$USERS.log" 2>&1 || true
  kill "$SAMPLER"
  python3 scripts/load_summary.py "$OUT" "$USERS" >> "$OUT/summary.txt"
  tail -1 "$OUT/summary.txt"
done
