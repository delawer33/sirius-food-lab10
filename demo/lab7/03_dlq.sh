#!/usr/bin/env bash
# Шаг 5 методички: битое сообщение уходит в DLQ и не блокирует очередь.
source "$(dirname "$0")/../lib.sh"

step "1. Битое сообщение: строка not-json с ключом order.paid"
run queues
run 'mq_publish order.paid "not-json"'
pause 2
note "kitchen, delivery и event_log получили копию, каждый отклонил её без повтора → свой *_dlq"
run queues

step "Что лежит в kitchen_dlq: тело и заголовок x-death от брокера (откуда и почему)"
run "curl -s -u \$MQ_AUTH -H 'Content-Type: application/json' -X POST \$MQ_API/queues/%2F/kitchen_dlq/get -d '{\"count\": 1, \"ackmode\": \"ack_requeue_true\", \"encoding\": \"auto\"}' | jq '.[0] | {payload, death: .properties.headers[\"x-death\"][0] | {queue, reason, exchange, \"routing-keys\"}}'"

step "Очередь не заблокирована: следующий нормальный заказ проходит"
run 'STUDENT=$(login student@sirius.ru)'
order 2
pause 2
run "sql \"select * from kitchen_orders order by id desc limit 1\""

step "2. Временный сбой: база кухни недоступна → 3 попытки → DLQ"
run "docker compose stop db"
run "mq_publish order.paid '{\"event_id\": \"'\$(cat /proc/sys/kernel/random/uuid)'\", \"order_id\": 999}'"
pause 6
note "в терминале Kitchen: попытка 1/3, 2/3 → вернул в очередь, 3/3 → kitchen_dlq"
run "docker compose start db"
run queues
