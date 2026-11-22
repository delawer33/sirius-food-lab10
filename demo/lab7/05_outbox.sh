#!/usr/bin/env bash
# Transactional Outbox: RabbitMQ лежит в момент оплаты — событие не теряется.
source "$(dirname "$0")/../lib.sh"

step "Останавливаем RabbitMQ"
run "docker compose stop rabbitmq"

step "Заказ оформляется как обычно: API не зависит от брокера"
run 'STUDENT=$(login student@sirius.ru)'
order 1
note "заказ создан, хотя брокер лежит"
pause 4

step "Событие ждёт в outbox: published_at пуст"
run "sql \"select id, routing_key, payload::json->>'order_id' as order_id, published_at, attempts from outbox where published_at is null\""
note "в терминале Outbox: «RabbitMQ недоступен ...; в outbox ждут 1»"

step "Поднимаем RabbitMQ"
run "docker compose start rabbitmq"
note "ждём, пока брокер примет соединения и релей переподключится"
for _ in $(seq 30); do
  [ "$(sql_value "select count(*) from outbox where published_at is null")" = 0 ] && break
  sleep 1
done
pause 3

step "Релей отправил событие, кухня и доставка его получили"
run "sql \"select id, routing_key, published_at::time(0), attempts from outbox where payload::json->>'order_id' = '$ORDER'\""
run "sql \"select * from kitchen_orders where order_id = $ORDER\""
run "sql \"select * from delivery_requests where order_id = $ORDER\""
