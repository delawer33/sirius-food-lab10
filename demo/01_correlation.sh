#!/usr/bin/env bash
# Расследование заказа demo-42: один correlation_id в ответе API, в логах
# монолита, релея outbox и всех consumer'ов, в Jaeger и в Grafana.
source "$(dirname "$0")/lib.sh"
ID=${1:-demo-42}

step "Студент входит"
run 'STUDENT=$(login student@sirius.ru); echo "токен: ${STUDENT:0:25}..."'

step "Заказ с X-Correlation-ID: $ID — тот же ID возвращается в ответе"
run "curl -s -D - -o /tmp/order.json -X POST $API/orders/create -H \"Authorization: Bearer \$STUDENT\" -H 'Content-Type: application/json' -H 'X-Correlation-ID: $ID' -d '{\"item_id\": 1, \"quantity\": 1}' | grep -iE '^(HTTP|x-correlation-id)'; cat /tmp/order.json; echo"
ORDER=$(jq -r .order_id /tmp/order.json)
pause 3

step "Монолит: запрос и order_created"
run "logs_of sirius_app $ID"

step "Релей outbox взял ID из строки outbox и положил в заголовок сообщения"
run "logs_of sirius_outbox_relay $ID"

step "Кухня получила тот же ID из заголовка сообщения"
run "logs_of sirius_kitchen $ID"

step "И остальные consumer'ы того же события"
run "logs_of sirius_delivery_worker $ID"
run "logs_of sirius_event_log $ID"

step "trace_id из лога — ключ к трейсу в Jaeger"
TRACE=$(logs_of sirius_app "$ID" | jq -r 'select(.message == "order_created") | .trace_id' | tail -1)
note "заказ $ORDER, трейс: http://localhost:16686/trace/$TRACE"
note "span'ы уходят в Jaeger пачками раз в 5 с — ждём"; sleep 6
run "curl -s http://localhost:16686/api/traces/$TRACE | jq -r '.data[0] | .processes as \$p | .spans | sort_by(.startTime) | .[] | \"\(\$p[.processID].serviceName)\t\(.operationName)\t\(.duration / 1000) ms\"' | column -t -s \$'\t'"
