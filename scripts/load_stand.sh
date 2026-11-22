#!/usr/bin/env bash
# API для нагрузочного теста: PostgreSQL и Redis в Docker, uvicorn на 8010.
#
#   ./scripts/load_stand.sh up        # контейнеры lab10-pg (5442) и lab10-redis (6390)
#   WORKERS=1 ./scripts/load_stand.sh api   # миграции, студенты load1..20, uvicorn
#   ./scripts/load_stand.sh down      # остановить контейнеры (данные остаются)
#
# Rate limit выключен: все пользователи Locust приходят с одного IP.
# Celery-задачи уходят в Redis, воркер для замера API не нужен.
set -eu
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"

case "${1:-api}" in
up)
  docker start lab10-pg 2>/dev/null || docker run -d --name lab10-pg -e POSTGRES_USER=sirius \
    -e POSTGRES_PASSWORD=sirius -e POSTGRES_DB=sirius_food -p 127.0.0.1:5442:5432 postgres:16-alpine
  docker start lab10-redis 2>/dev/null || docker run -d --name lab10-redis -p 127.0.0.1:6390:6379 redis:7-alpine
  ;;
down)
  docker stop lab10-pg lab10-redis
  ;;
api)
  export SECRET_KEY=lab10-load-secret-key-at-least-32-characters
  export DATABASE_URL=postgresql://sirius:sirius@127.0.0.1:5442/sirius_food
  export REDIS_URL=redis://127.0.0.1:6390/0 CELERY_BROKER_URL=redis://127.0.0.1:6390/1
  export RATE_LIMIT_ENABLED=False DEBUG=False
  export OTEL_EXPORTER_OTLP_ENDPOINT= SENTRY_DSN=
  # kill -ABRT <pid> — стеки всех потоков в stderr, если API завис.
  export PYTHONFAULTHANDLER=1
  "$PY" -m alembic upgrade head
  "$PY" -m scripts.seed_load
  exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8010}" \
    --workers "${WORKERS:-1}" --no-access-log
  ;;
esac
