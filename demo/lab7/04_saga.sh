#!/usr/bin/env bash
# Saga (хореография): курьера нет → delivery.failed → отмена заказа и возврат денег.
source "$(dirname "$0")/../lib.sh"

step "Все курьеры уходят со смены (таблица сервиса доставки)"
run "sql \"update courier_shifts set on_shift = false\""
run "sql \"select email, balance from users where email = 'student@sirius.ru'\""

step "Студент оформляет заказ"
run 'STUDENT=$(login student@sirius.ru)'
order 1
pause 3

step "Цепочка событий по заказу $ORDER (outbox монолита; delivery.failed шлёт сервис доставки — смотрите терминал Events)"
run "sql \"select id, routing_key, payload::json->>'reason' as reason, published_at::time(0) from outbox where payload::json->>'order_id' = '$ORDER' order by id\""
run "sql \"select order_id, status, free_couriers from delivery_requests where order_id = $ORDER\""

step "Компенсация выполнена: заказ отменён, деньги вернулись, кухня сняла заказ"
run "sql \"select id, status, total_cost from orders where id = $ORDER\""
run "sql \"select email, balance from users where email = 'student@sirius.ru'\""
run "sql \"select order_id, amount, reason from refunds where order_id = $ORDER\""
run "sql \"select order_id, status from kitchen_orders where order_id = $ORDER\""

step "Компенсация идемпотентна: шлём delivery.failed по этому заказу ещё раз"
run "mq_publish delivery.failed '{\"event_id\": \"'\$(cat /proc/sys/kernel/random/uuid)'\", \"order_id\": $ORDER, \"reason\": \"повтор вручную\"}'"
pause 2
run "sql \"select count(*) as refunds, sum(amount) from refunds where order_id = $ORDER\""
run "sql \"select email, balance from users where email = 'student@sirius.ru'\""
note "в терминале Saga: «Повтор ...: заказ уже отменён, компенсация не нужна»"

step "Курьеры возвращаются на смену"
run "sql \"update courier_shifts set on_shift = true\""
