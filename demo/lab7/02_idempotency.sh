#!/usr/bin/env bash
# Шаг 7 методички: повторная доставка с тем же event_id не создаёт дубль.
source "$(dirname "$0")/../lib.sh"

ORDER=$(sql_value "select (payload::json->>'order_id') from outbox where routing_key = 'order.paid' order by id desc limit 1")
step "Берём последнее опубликованное order.paid (заказ $ORDER) прямо из outbox"
run "EVENT=\$(sql_value \"select payload from outbox where routing_key = 'order.paid' order by id desc limit 1\"); echo \$EVENT"

step "Публикуем его ещё два раза через HTTP API RabbitMQ (как кнопкой Publish message в UI)"
run 'mq_publish order.paid "$EVENT"'
run 'mq_publish order.paid "$EVENT"'
pause 2

step "Дублей нет: одна строка в kitchen_orders и одна заявка доставки"
run "sql \"select order_id, count(*) from kitchen_orders where order_id = $ORDER group by order_id\""
run "sql \"select consumer, left(event_id, 8) as event, processed_at::time(0) from processed_events where event_id = '\$(jq -r .event_id <<< \"\$EVENT\")'\""
run "sql \"select order_id, status from delivery_requests where order_id = $ORDER\""
note "в терминалах Kitchen и Delivery: «Повтор event=... — уже обработано, пропускаю»"
