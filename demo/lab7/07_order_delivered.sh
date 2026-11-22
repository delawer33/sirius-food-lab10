#!/usr/bin/env bash
# Второе событие OrderDelivered: полный путь заказа до доставки.
# Нужен delivery_server.py (gRPC) из лабораторной № 6.
source "$(dirname "$0")/../lib.sh"

run 'STUDENT=$(login student@sirius.ru); COOK=$(login cook@sirius.ru); ADMIN=$(login admin@sirius.ru); COURIER=$(login courier@sirius.ru)'

step "Заказ → кухня приготовила → администратор назначил курьера"
order 1
run "curl -s -X POST $API/kitchen/orders/$ORDER/ready -H \"Authorization: Bearer \$COOK\""
echo
run "curl -s -X POST $API/delivery/assign -H \"Authorization: Bearer \$ADMIN\" -H 'Content-Type: application/json' -d '{\"order_id\": $ORDER, \"courier_id\": 4}'"
echo
DELIVERY=$(sql_value "select max(id) from deliveries where order_id = $ORDER")

step "Курьер завершает доставку"
run "curl -s -X PATCH $API/delivery/$DELIVERY/complete -H \"Authorization: Bearer \$COURIER\""
echo
pause 2

step "order.delivered записан в outbox вместе со статусом delivered и опубликован"
run "sql \"select id, routing_key, published_at::time(0) from outbox where payload::json->>'order_id' = '$ORDER' order by id\""
run "sql \"select id, status from orders where id = $ORDER\""
note "в терминале Events: order.delivered {...}"
