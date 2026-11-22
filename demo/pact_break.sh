#!/usr/bin/env bash
# Pact ловит несовместимость: в событии OrderPaid order_id переименовывается
# в orderId, provider-тест монолита падает. Затем файл возвращается как был.
#
#   ./demo/pact_break.sh
set -u
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
trap 'git checkout -q app/domain/events.py' EXIT

echo "== Контракт цел"
"$PY" -m pytest tests/pact -q -p no:warnings 2>&1 | tail -1

echo; echo "== order_id -> orderId в app/domain/events.py"
sed -i 's/_event(ORDER_PAID, "OrderPaid", order_id=order_id,/_event(ORDER_PAID, "OrderPaid", orderId=order_id,/' app/domain/events.py
git diff --unified=0 app/domain/events.py | grep '^[-+] '

echo; echo "== Provider-тест монолита"
"$PY" -m pytest tests/pact/test_monolith_provider.py -q -p no:warnings 2>&1 \
  | sed 's/\x1b\[[0-9;]*m//g' | grep -E "Verifying a pact|missing the following keys|has a matching body|passed|failed"
