# Общие помощники демо-скриптов. Каждая команда печатается перед запуском,
# чтобы было видно, что именно выполняется: curl к API, psql к БД,
# rabbitmqctl и HTTP API брокера. Ничего своего между вами и системой нет.
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

API=${API:-http://127.0.0.1:8010}
MQ_API=${MQ_API:-http://localhost:15672/api}
MQ_AUTH=${MQ_AUTH:-sirius:sirius}
PASSWORD=${DEMO_PASSWORD:-sirius-demo}

step() { printf '\n\033[1;36m=== %s ===\033[0m\n' "$*"; }
note() { printf '\033[2m# %s\033[0m\n' "$*"; }
run()  { printf '\033[1;33m$ %s\033[0m\n' "$*"; eval "$@"; }
pause() { note "пауза ${1:-2} с: смотрите терминалы consumer'ов"; sleep "${1:-2}"; }

# SQL в контейнере PostgreSQL.
sql() { docker compose exec -T db psql -U sirius -d sirius_food -c "$1"; }
sql_value() { docker compose exec -T db psql -U sirius -d sirius_food -At -c "$1"; }

# Очереди глазами самого брокера.
queues() {
  docker compose exec -T rabbitmq rabbitmqctl list_queues --quiet name messages_ready messages_unacknowledged |
    { read -r header; echo "$header"; sort; } | column -t
}

login() {
  local response
  response=$(curl -s -X POST "$API/auth/login" -H 'Content-Type: application/json' \
    -d "{\"email\": \"$1\", \"password\": \"$PASSWORD\"}")
  jq -er .access_token <<< "$response" 2>/dev/null || { echo "вход $1 не удался: $response" >&2; exit 1; }
}

# Публикация в exchange через HTTP API RabbitMQ — то же, что кнопка
# «Publish message» в веб-интерфейсе: $1 — routing key, $2 — тело.
mq_publish() {
  jq -n --arg key "$1" --arg body "$2" \
    '{properties: {delivery_mode: 2}, routing_key: $key, payload: $body, payload_encoding: "string"}' |
    curl -s -u "$MQ_AUTH" -H 'Content-Type: application/json' \
      -X POST "$MQ_API/exchanges/%2F/sirius_events/publish" -d @-
  echo
}

# Заказ от студента ($STUDENT — его токен): $1 — id блюда. Номер заказа — в $ORDER.
order() {
  run "RESP=\$(curl -s -X POST $API/orders/create -H \"Authorization: Bearer \$STUDENT\" -H 'Content-Type: application/json' -d '{\"item_id\": $1, \"quantity\": 1}'); echo \"\$RESP\""
  ORDER=$(jq -er .order_id <<< "$RESP") || { echo "заказ не создан" >&2; exit 1; }
}

# JSON-логи контейнера с этим correlation_id: $1 — контейнер, $2 — ID.
# Строки, которые не JSON (если вдруг есть), jq пропускает.
logs_of() {
  docker logs "$1" 2>&1 | jq -cR --arg id "$2" 'fromjson? | select(.correlation_id == $id)'
}
