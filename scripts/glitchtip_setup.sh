#!/usr/bin/env bash
# Один раз после первого docker compose up: пользователь, организация и проект
# в GlitchTip. DSN проекта и токен API записываются в .env, сервисы
# пересоздаются с SENTRY_DSN. Повторный запуск ничего не дублирует.
cd "$(dirname "$0")/.." || exit 1
EMAIL=${GLITCHTIP_EMAIL:-admin@sirius.ru}
PASSWORD=${DEMO_PASSWORD:-sirius-demo}

OUT=$(docker compose exec -T -e EMAIL="$EMAIL" -e PASSWORD="$PASSWORD" glitchtip ./manage.py shell -c '
import os
from apps.api_tokens.models import APIToken
from apps.organizations_ext.models import Organization, OrganizationUserRole
from apps.projects.models import Project, ProjectKey
from apps.users.models import User

user = User.objects.filter(email=os.environ["EMAIL"]).first()
if user is None:
    user = User.objects.create_superuser(email=os.environ["EMAIL"], password=os.environ["PASSWORD"])
org, created = Organization.objects.get_or_create(slug="sirius", defaults={"name": "Sirius"})
if created:
    org.add_user(user, role=OrganizationUserRole.OWNER)
project, _ = Project.objects.get_or_create(organization=org, name="sirius-food", defaults={"platform": "python"})
key = ProjectKey.objects.filter(project=project).first() or ProjectKey.objects.create(project=project)
token = APIToken.objects.filter(user=user, label="demo").first()
if token is None:
    token = APIToken.objects.create(user=user, label="demo", scopes=1153)  # project:read, event:read, org:read — биты 0, 7, 10
print(f"DSN http://{key.public_key_hex}@glitchtip:8000/{project.id}")
print(f"TOKEN {token.token}")
') || { echo "$OUT"; exit 1; }

# Адрес glitchtip:8000 — внутри сети compose, туда отправляют ошибки сервисы.
DSN=$(awk '/^DSN /{print $2}' <<< "$OUT")
TOKEN=$(awk '/^TOKEN /{print $2}' <<< "$OUT")
[ -n "$DSN" ] && [ -n "$TOKEN" ] || { echo "$OUT"; exit 1; }
touch .env
sed -i '/^SENTRY_DSN=/d; /^GLITCHTIP_TOKEN=/d' .env
printf 'SENTRY_DSN=%s\nGLITCHTIP_TOKEN=%s\n' "$DSN" "$TOKEN" >> .env
echo "SENTRY_DSN=$DSN записан в .env"
docker compose up -d app delivery_server outbox_relay kitchen delivery_worker saga event_log
echo "GlitchTip: http://localhost:8090, $EMAIL / $PASSWORD"
