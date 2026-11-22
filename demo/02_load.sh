#!/usr/bin/env bash
# Нагрузка для графиков Grafana: меню и заказы в течение $1 секунд (по умолчанию 60).
# Каждый заказ — со своим correlation_id load-N, его можно найти в логах.
source "$(dirname "$0")/lib.sh"
SECONDS_TOTAL=${1:-60}

STUDENT=$(login student@sirius.ru)
note "нагрузка $SECONDS_TOTAL с: 10 запросов меню и 1 заказ в секунду"
end=$((SECONDS + SECONDS_TOTAL)); n=0
while [ $SECONDS -lt $end ]; do
  for _ in $(seq 10); do curl -s -o /dev/null "$API/menu/items" & done
  n=$((n + 1))
  curl -s -o /dev/null -X POST "$API/orders/create" -H "Authorization: Bearer $STUDENT" \
    -H 'Content-Type: application/json' -H "X-Correlation-ID: load-$n" -d '{"item_id": 2, "quantity": 1}' &
  sleep 1
done
wait
note "отправлено заказов: $n — откройте http://localhost:3000"
