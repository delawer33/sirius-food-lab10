# Сириус.Еда: бэкенд для витрины ЛР № 8

Копия бэкенда после ЛР № 9. Для ЛР № 8 (SSR-витрина, `../sirius-food-frontend`)
изменено немного:

- `GET /menu/items/{id}` — карточка блюда или 404 (`app/modules/menu/router.py`,
  тест `test_get_item` в `tests/api/test_menu_cache.py`);
- демо-меню из 8 блюд, включая Сырники (`scripts/seed_demo.py`);
- CORS для `http://localhost:3000` — его использует CSR-страница `/menu-csr`;
- `docker compose up -d` поднимает только db, redis, rabbitmq, migrate и app.
  Остальное из ЛР № 9 — `--profile full`;
- `scripts/run_local.sh` — запуск без Docker: SQLite, порт 8010. Этим путём
  проверялась витрина. Вариант через Docker не проверял.

Ниже — README ЛР № 9 без изменений.

---

# Сириус.Еда: наблюдаемость

Лабораторная № 9. Один `correlation_id` проходит через монолит, outbox,
RabbitMQ и все consumer'ы. Логи — JSON в stdout, метрики — в Prometheus и
Grafana, ошибки — в Sentry (GlitchTip), трейсы — в Jaeger.

| Уровень | Что требуется | Где проверить |
|---|---|---|
| 6–7 | correlation_id во всех сервисах, JSON-логи, Prometheus | `demo/01_correlation.sh`, http://localhost:9090/targets |
| 8 | дашборд Grafana, расследование `demo-42` | http://localhost:3000, `demo/02_load.sh` |
| 9 | ошибка в Sentry с correlation_id | `demo/03_sentry.sh`, http://localhost:8090 |
| 10 | трейс заказа в Jaeger | http://localhost:16686, ссылка в выводе `demo/01` |

## Что сделано

- **Correlation ID.** Middleware `app/core/correlation.py` берёт `X-Correlation-ID`
  из запроса или создаёт UUID, кладёт в `request.state` и в contextvars логов,
  возвращает в ответе. Событие сначала пишется в outbox, поэтому ID и
  `traceparent` сохраняются в строке outbox (миграция `0007`). Релей кладёт их в
  заголовки сообщения, consumer достаёт и привязывает к своим логам.
- **JSON-логи** (`observability/logging.py`). structlog и обычный `logging`
  (uvicorn, SQLAlchemy) выводятся одним форматтером, каждая строка — JSON с
  `service`, `correlation_id`, `trace_id`, `order_id`, `event_id`.
- **Метрики.** Монолит: RED на `/metrics` (prometheus-fastapi-instrumentator)
  и свои `sirius_orders_created_total`, `sirius_cache_requests_total`. Consumer'ы и
  релей: обработанные события по исходу (`ok/retry/dlq/bad`), время обработки,
  неотправленные события outbox — на порту 9100. RabbitMQ — встроенный плагин
  `rabbitmq_prometheus`, Redis — `redis_exporter`.
- **Grafana.** Источник и дашборд «Сириус.Еда» подключаются сами при старте
  (`monitoring/grafana/`): 10 панелей — RPS, p95, 5xx, заказы, очереди,
  hit rate Redis и кеша меню, события consumer'ов, outbox.
- **Sentry.** `observability/errors.py`, тег `correlation_id` на каждой ошибке.
  Вместо sentry.io — GlitchTip в compose: тот же протокол и тот же `sentry-sdk`,
  но без регистрации и без интернета. Для sentry.io достаточно заменить `SENTRY_DSN`.
- **OpenTelemetry.** Span'ы HTTP, SQL, gRPC, публикации из outbox и обработки в
  каждом consumer'е уходят в Jaeger по OTLP. Контекст через RabbitMQ передаётся
  заголовком `traceparent`.
- Вся система в Docker: `Dockerfile` (один образ на все процессы),
  `docker-compose.yml` (16 контейнеров).

## Как показать

### Запуск

```bash
docker compose up -d --build
./scripts/glitchtip_setup.sh   # один раз: проект в GlitchTip, DSN в .env, перезапуск сервисов
```

| Что | Адрес |
|---|---|
| API | http://localhost:8010 (порт 8000 на этой машине занят) |
| Grafana | http://localhost:3000, admin / admin |
| Prometheus | http://localhost:9090/targets |
| Jaeger | http://localhost:16686 |
| GlitchTip | http://localhost:8090, admin@sirius.ru / sirius-demo |
| RabbitMQ | http://localhost:15672, sirius / sirius |

Остановить: `docker compose stop` (данные в томах сохраняются).

### Расследование заказа demo-42

```bash
./demo/01_correlation.sh          # или ./demo/01_correlation.sh свой-id
```

Скрипт входит студентом, отправляет заказ с `X-Correlation-ID: demo-42` и
показывает логи всех сервисов с этим ID. Вручную то же самое:

```bash
curl -v -X POST http://127.0.0.1:8010/orders/create \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -H "X-Correlation-ID: demo-42" -d '{"item_id": 1, "quantity": 1}'
docker logs sirius_app | jq 'select(.correlation_id == "demo-42")'
docker logs sirius_kitchen | jq 'select(.correlation_id == "demo-42")'
```

Вывод живого прогона — `docs/demo/01_correlation.txt`. Что в нём видно:

- в ответе `x-correlation-id: demo-42`;
- `sirius_app`: `order_created` и `http_request`; `sirius_outbox_relay`:
  `event_published`; `sirius_kitchen`: `order_received`; плюс доставка и журнал событий;
- у всех этих строк один `trace_id`. Скрипт печатает ссылку на трейс в Jaeger и
  его span'ы: HTTP-запрос и SQL монолита → публикация из outbox → обработка в
  трёх consumer'ах с их SQL;
- если запустить скрипт дважды, у `demo-42` будет два заказа и **два разных**
  `trace_id`: correlation_id — бизнес-операция, trace_id — один технический вызов.

### Метрики в Grafana

```bash
./demo/02_load.sh 60    # минута нагрузки: 10 запросов меню и 1 заказ в секунду
```

Дашборд «Сириус.Еда» (http://localhost:3000) показывает всплеск RPS, p95 по
эндпоинтам, заказы в секунду, обработку событий в очередях. Чтобы увидеть
метрики за время конкретного заказа, возьмите `timestamp` из его лога и
выделите этот интервал на графике.

### Ошибка в Sentry

```bash
./demo/03_sentry.sh
```

`GET /debug/error` с `X-Correlation-ID: demo-500` → ответ 500 с тем же
заголовком, в логе `sirius_app` — `request_failed` со стектрейсом, в GlitchTip —
issue `RuntimeError` с тегами `correlation_id: demo-500` и `service: sirius-app`.
Поиск в GlitchTip: `correlation_id:demo-500`. Вывод — `docs/demo/03_sentry.txt`.

Consumer тоже отправляет в Sentry, но только окончательный отказ (сообщение
ушло в DLQ), с тем correlation_id, что пришёл в заголовке сообщения.

### Тесты

```bash
.venv/bin/pytest -q
```

341 тест. Наблюдаемость — `tests/unit/test_observability.py`: ID от клиента
и сгенерированный, отбор подозрительных ID, ID в строке outbox, в заголовке
публикуемого сообщения, в логах consumer'а и в потоке обработчика.

## Как устроено

```
клиент ─X-Correlation-ID─► app ─(одна транзакция)─► orders + outbox{correlation_id, traceparent}
                                                          │
                       outbox_relay ◄─────────────────────┘
                            │ headers: X-Correlation-ID, traceparent
                            ▼
                     RabbitMQ sirius_events ─► kitchen, delivery_worker, event_log, saga
```

- Пакет `observability/` общий: им пользуются монолит, сервис доставки и
  consumer'ы. Каждый процесс вызывает `observability.setup("имя")`. Трейсы
  включаются переменной `OTEL_EXPORTER_OTLP_ENDPOINT`, Sentry — `SENTRY_DSN`;
  без них (как в тестах) всё работает, просто ничего не отправляется.
- Клиентский `X-Correlation-ID` попадает в логи и заголовки, поэтому принимается
  только `[A-Za-z0-9._:-]{1,128}`, иначе генерируется новый.
- В метках метрик только значения из коротких списков (`queue`, `result`,
  `handler`). `order_id` или `correlation_id` в метке создали бы временной ряд на
  каждый заказ; их место — в логах.
- В Sentry уходит только окончательный отказ consumer'а (сообщение ушло в DLQ),
  а не каждая повторная попытка.

## Отличия от методички

1. **Correlation ID через outbox.** В методичке событие публикуется прямо из
   запроса. Здесь его публикует релей позже, в другом процессе, поэтому ID и
   `traceparent` хранятся в строке outbox.
2. **Трассировка RabbitMQ вручную**, а не автоинструментацией aio-pika: она
   привязала бы публикацию к циклу релея, а не к запросу, создавшему заказ.
3. **GlitchTip вместо sentry.io**: ничего не нужно регистрировать, работает на
   защите без интернета. Код тот же — `sentry-sdk`.
4. **Ошибка 500** — `GET /debug/error` (только при `DEBUG`). `GET /orders/999999`
   в проекте корректно отвечает 404.
5. **Порт API 8010**: 8000 на этой машине занят другим проектом. Prometheus
   ходит к приложению внутри сети compose (`app:8000`), а не через
   `host.docker.internal`.
6. **Прошлые демо** (лабораторная № 7) перенесены в `demo/lab7/`.

## Контрольные вопросы

**1. Observability и мониторинг.** Мониторинг отвечает на заранее заданные
вопросы: жив ли сервис, превышен ли порог. Observability позволяет ответить
на новый вопрос по уже собранным логам, метрикам и трейсам — например, почему
один заказ дошёл до кухни, а другой нет.

**2. Зачем correlation_id.** Связать все записи одной бизнес-операции в разных
сервисах. Без него логи монолита и кухни сопоставляются только по времени, а
при нескольких заказах в секунду это угадывание.

**3. Почему stdout, а не файл.** Docker сам собирает stdout (`docker logs`), а
файл внутри контейнера пропадает при пересоздании и не виден снаружи. При
нескольких репликах файлы лежали бы на разных машинах.

**4. correlation_id и trace_id.** correlation_id задаёт приложение (или клиент),
он живёт всю бизнес-операцию и бывает в логах, БД, тикетах. trace_id создаёт
OTel SDK на один технический вызов. В демо у двух заказов с `demo-42` один
correlation_id и два trace_id.

**5. RED.** Rate — запросы в секунду, Errors — доля ошибок, Duration —
время ответа. Три метрики на каждый эндпоинт (панели RPS, 5xx, p95).

**6. Span и trace.** Span — один шаг: имя, начало, длительность, родитель,
атрибуты (SQL-запрос, обработка сообщения кухней). Trace — дерево span'ов
одного вызова через все сервисы.

**7. Context propagation.** Передача trace_id и id родительского span'а в
следующий сервис заголовком `traceparent`: в HTTP, метаданных gRPC и здесь — в
заголовках сообщения RabbitMQ. Заголовок не копит данные, каждый сервис сам
отправляет свои span'ы в Jaeger.

**8. Sentry и логи.** Логи пишут всё подряд, их надо искать. Sentry собирает
только ошибки, группирует одинаковые, считает повторы, показывает стектрейс,
запрос и теги и сам оповещает.

**9. Кардинальность метрик.** Число уникальных сочетаний меток. Каждое — отдельный
временной ряд в памяти Prometheus. Метка с `order_id` или `user_id` даёт ряд на
каждый заказ и рано или поздно кладёт Prometheus. Поэтому такие поля — в логах.

**10. request.state и call_next.** `request.state` — место для данных одного
запроса: middleware кладёт туда correlation_id, эндпоинт читает. `call_next`
передаёт запрос дальше по цепочке и возвращает ответ, после чего middleware
может дописать заголовок `X-Correlation-ID`.
