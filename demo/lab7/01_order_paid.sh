#!/usr/bin/env bash
# Шаг 6 методички: событие OrderPaid доходит до кухни и доставки независимо.
source "$(dirname "$0")/../lib.sh"

step "Студент входит и оформляет заказ (деньги списываются — заказ оплачен)"
run 'STUDENT=$(login student@sirius.ru); echo "токен: ${STUDENT:0:25}..."'
order 1
pause 2

step "Событие легло в outbox той же транзакцией, релей отправил его в RabbitMQ"
run "sql \"select id, routing_key, left(event_id, 8) as event, created_at::time(0), published_at::time(0) from outbox order by id desc limit 3\""

step "Кухня и доставка получили одно и то же событие, каждая в свою очередь"
run "sql \"select * from kitchen_orders where order_id = $ORDER\""
run "sql \"select * from delivery_requests where order_id = $ORDER\""

step "Очереди пусты: всё прочитано и подтверждено (ack)"
run queues
