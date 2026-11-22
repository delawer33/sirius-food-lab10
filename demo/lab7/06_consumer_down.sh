#!/usr/bin/env bash
# Consumer остановлен: сообщение ждёт в очереди и обрабатывается после старта.
source "$(dirname "$0")/../lib.sh"

step "Останавливаем кухню"
run "./run_all.sh stop kitchen"

step "Заказ при остановленной кухне"
run 'STUDENT=$(login student@sirius.ru)'
order 2
note "счётчики quorum-очереди в rabbitmqctl обновляются раз в ~5 с"
pause 7

step "Доставка уже обработала, а сообщение кухни лежит в kitchen_queue"
run queues
run "sql \"select * from kitchen_orders where order_id = $ORDER\""
run "sql \"select order_id, status from delivery_requests where order_id = $ORDER\""

step "Запускаем кухню: она забирает сообщение из очереди"
run "./run_all.sh start kitchen"
pause 7
run queues
run "sql \"select * from kitchen_orders where order_id = $ORDER\""
