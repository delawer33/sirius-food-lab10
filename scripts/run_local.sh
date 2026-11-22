#!/usr/bin/env bash
# Бэкенд для витрины ЛР № 8 без Docker: SQLite-файл, кеш Redis выключен, порт 8010.
# Миграции и демо-меню (Сырники и др.) применяются при каждом запуске, повторно — без дублей.
#
#   PY=.venv/bin/python ./scripts/run_local.sh
set -eu
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"

export SECRET_KEY=lab8-local-secret-key-at-least-32-characters
export DATABASE_URL=sqlite:///./lab8.db
export DEBUG=True CACHE_ENABLED=False RATE_LIMIT_ENABLED=False NOTIFICATIONS_MODE=sync
export ALLOWED_ORIGINS='["http://localhost:3000"]'
export OTEL_EXPORTER_OTLP_ENDPOINT= SENTRY_DSN=

"$PY" -m alembic upgrade head
"$PY" -m scripts.seed_demo
exec "$PY" -m uvicorn app.main:app --port "${PORT:-8010}"
