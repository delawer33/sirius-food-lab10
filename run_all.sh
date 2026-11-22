#!/usr/bin/env bash
# Вся система одной командой.
#
#   ./run_all.sh start          # БД, Redis, RabbitMQ + 7 процессов в фоне
#   ./run_all.sh logs           # логи всех процессов в одном терминале
#   ./run_all.sh stop           # остановить процессы и контейнеры
#   ./run_all.sh start kitchen  # перезапустить один процесс
#   ./run_all.sh stop kitchen   # остановить один процесс
#
# Логи: docs/demo/logs/<имя>.log
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate
source stand_env.sh
export PYTHONUNBUFFERED=1

LOGS=docs/demo/logs
PIDS=.pids
mkdir -p "$LOGS" "$PIDS"

declare -A CMD=(
  [uvicorn]="uvicorn app.main:app --port 8010"
  [delivery_server]="python delivery_server.py"
  [outbox_relay]="python -m app.workers.outbox_relay"
  [kitchen]="python -m app.workers.kitchen_consumer"
  [delivery_worker]="python delivery_worker.py"
  [saga]="python -m app.workers.saga_consumer"
  [event_log]="python -m app.workers.event_log"
)
ORDER="uvicorn delivery_server outbox_relay kitchen delivery_worker saga event_log"

stop_one() {
  [ -f "$PIDS/$1" ] && kill "$(cat "$PIDS/$1")" 2>/dev/null
  rm -f "$PIDS/$1"
}

start_one() {
  stop_one "$1"
  nohup ${CMD[$1]} >> "$LOGS/$1.log" 2>&1 &
  echo $! > "$PIDS/$1"
  echo "  $1 запущен, лог $LOGS/$1.log"
}

action=$1; shift
names=${*:-$ORDER}

case "$action" in
  start)
    if [ -z "$*" ]; then
      docker compose up -d db redis rabbitmq
      alembic upgrade head
      python -m scripts.seed_demo
      python -m app.workers.dlq_setup   # ждёт, пока RabbitMQ стартует
    fi
    for n in $names; do start_one "$n"; done
    ;;
  stop)
    for n in $names; do stop_one "$n"; done
    [ -z "$*" ] && docker compose stop
    ;;
  logs)
    tail -n 5 -f $(for n in $ORDER; do echo "$LOGS/$n.log"; done)
    ;;
  *)
    sed -n '2,10p' "$0"
    ;;
esac
