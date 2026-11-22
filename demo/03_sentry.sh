#!/usr/bin/env bash
# Ошибка 500 попадает в Sentry (GlitchTip) с тегом correlation_id.
# Нужен scripts/glitchtip_setup.sh: он пишет GLITCHTIP_TOKEN в .env.
source "$(dirname "$0")/lib.sh"
ID=${1:-demo-500}
GT=http://localhost:8090/api/0
TOKEN=$(sed -n 's/^GLITCHTIP_TOKEN=//p' .env)
gt() { curl -s -H "Authorization: Bearer $TOKEN" "$GT$1"; }

step "Необработанная ошибка в эндпоинте (GET /debug/error, только при DEBUG)"
run "curl -s -i $API/debug/error -H 'X-Correlation-ID: $ID' | grep -iE '^(HTTP|x-correlation-id)|Internal'"

step "В логе монолита — request_failed со стектрейсом и тем же ID"
run "logs_of sirius_app $ID | jq -c '{message, level, status, correlation_id, trace_id, error: (.exception | split(\"\n\") | map(select(length > 0)) | last)}'"
note "GlitchTip обрабатывает событие в фоне — ждём"; sleep 5

step "Ошибка в GlitchTip: issue и последнее событие с тегами"
run "gt '/projects/sirius/sirius-food/issues/?query=correlation_id:$ID' | jq -c '.[] | {id, title, culprit, count, lastSeen}'"
ISSUE=$(gt "/projects/sirius/sirius-food/issues/?query=correlation_id:$ID" | jq -r '.[0].id')
run "gt /issues/$ISSUE/events/latest/ | jq -c '{eventID, tags: [.tags[] | select(.key | test(\"correlation_id|service|url|transaction\")) | {(.key): .value}] | add}'"
note "в браузере: http://localhost:8090/sirius/issues/$ISSUE"
