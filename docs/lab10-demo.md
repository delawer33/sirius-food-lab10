# ЛР № 10 руками: как показать

Сдаём на 6 баллов: интеграционные тесты с Testcontainers работают, Locust показывает RPS
и latency, нагрузка выявляет узкое место. Порядок — как в разделе «Что сдавать» методички,
пункты 1–4. Только стандартные инструменты: `pytest`, `docker`, `psql`, `curl`, `top`, `grep`
и веб-интерфейс Locust.
Скрипт `scripts/load_stand.sh` только поднимает стенд: контейнеры и API с нужными настройками.
Каждый шаг прогнан на этом ноутбуке. Цифры нагрузки от прогона к прогону немного плавают.

## Подготовка

Все терминалы открываются в папке проекта, в каждом активируется окружение:

```bash
cd "/home/delawer/all/coll/!4c/miki/lab10/sirius_food"
source .venv/bin/activate
```

Docker должен быть запущен. Порты: API стенда — 8020 (8000 занят другим проектом, 8010 —
стендом практики), PostgreSQL стенда — 5442, Redis — 6390, Locust — 8089.

## 1. Интеграционные тесты (пункт 1 «Что сдавать»)

Терминал B — следить за контейнерами:

```bash
watch -n 1 docker ps
```

Терминал A:

```bash
pytest tests/integration -v
```

Ответ: `12 passed` примерно за 20 с. Пока тесты идут, в терминале B появляются контейнеры
`postgres:16-alpine` и `rabbitmq:3.13-management` со случайными именами. После тестов
они исчезают. `watch` закрывается по Ctrl+C.

Пять тестов на PostgreSQL (`test_orders_postgres.py`):

| Тест | Что проверяет |
|---|---|
| `test_create_order_saves_to_db` | заказ через HTTP лёг в таблицу, баланс списан, OrderPaid в outbox |
| `test_rejected_order_leaves_no_trace` | отказ не оставил ни заказа, ни события, ни списания |
| `test_each_test_starts_with_clean_db` | данных прошлых тестов нет, id с единицы |
| `test_menu_item_from_postgres` | карточка блюда из PostgreSQL, на чужой id — 404 |
| `test_parallel_orders_do_not_overspend` | два заказа одновременно при деньгах на один — проходит один |

Остальные 7 — RabbitMQ из ЛР № 7.

## 2. Как работает Testcontainers (пункт 2)

Открыть `tests/integration/conftest.py`:

- строка 29 — образ `postgres:16-alpine`, тот же, что в `docker-compose.yml`;
- строка 34, `postgres_url` — контейнер поднимается один раз на сессию тестов;
- строка 49 — схема накатывается `alembic upgrade head`, как в проде, а не `create_all()`;
- строка 71 — перед каждым тестом `TRUNCATE ... RESTART IDENTITY`: база чистая, id с единицы.

Откат транзакции, как в методичке, здесь не сработает: обработчик заказа сам делает `commit`,
откатывать после теста нечего.

### Тест ловит настоящий баг

Последний тест нашёл гонку: два параллельных заказа оба проходили, баланс уходил в минус.
Исправление — блокировка строки пользователя. Если её убрать, тест падает.

Открыть `app/modules/orders/repository.py`, строка 52, и удалить из вызова
`with_for_update={"of": UserModel}, `. Должно остаться:

```python
        row = self.db.get(UserModel, user_id, populate_existing=True)
```

```bash
pytest tests/integration/test_orders_postgres.py -v
```

Ответ: `1 failed, 4 passed`, у `test_parallel_orders_do_not_overspend`
`AssertionError: assert ['ok', 'ok'] == ['ok', 'rejected']`: прошли оба заказа.
Вернуть файл:

```bash
git checkout app/modules/orders/repository.py
```

На SQLite в памяти, где идут остальные 361 тест, эту гонку не увидеть: там одно соединение
на все потоки.

## 3. Locust: RPS и latency под нагрузкой (пункт 3)

Нужны три терминала:

| Терминал | Для чего |
|---|---|
| A | стенд: контейнеры и API |
| B | Locust |
| C | наблюдение: CPU процесса API и соединения PostgreSQL |

Терминал A. Контейнеры `lab10-pg` и `lab10-redis`, затем API в один процесс с пулом
соединений по умолчанию. Миграции и 20 студентов для нагрузки накатываются при старте.

```bash
scripts/load_stand.sh up
```
```bash
WORKERS=1 scripts/load_stand.sh api
```

Ответ заканчивается строкой `Uvicorn running on http://127.0.0.1:8020`. Режим стенда:
rate limit выключен (все пользователи Locust приходят с одного IP), токен живёт 2 часа
(Locust входит один раз в начале теста).

Терминал B:

```bash
locust -f locustfile.py --host=http://127.0.0.1:8020
```

Открыть http://localhost:8089. Number of users — `50`, Ramp up — `10`, кнопка **START**.

Сценарий в `locustfile.py`: 70% запросов — витрина `GET /menu/items`, 20% — карточка блюда
`GET /menu/items/{id}`, 10% — заказ `POST /orders/create`. Пауза между запросами 1–3 с.
На вкладке **STATISTICS**: `Current RPS`, `95%ile (ms)`, `# Fails`.
На вкладке **CHARTS** — те же метрики графиками во времени.

Терминал C. CPU процесса API: 100% — одно ядро целиком. `pgrep` находит процесс uvicorn
и его воркеры. Выход из `top` — `q`.

```bash
top -c -p $(pgrep -u $USER -d, -f 'app.main:app|multiprocessing.spawn')
```

Соединения с базой по состоянию:

```bash
docker exec lab10-pg psql -U sirius -d sirius_food -c "select state, count(*) from pg_stat_activity where datname='sirius_food' group by 1"
```

Дальше поднимаем нагрузку: **EDIT** → Number of users → **Update**, сразу **RESET**, чтобы
цифры считались с новой ступени. Через минуту на каждой ступени смотрим цифры. На этом
прогоне было:

| Пользователи | RPS | p95, мс | Ошибки | CPU API |
|---|---|---|---|---|
| 50 | 22 | ~25 | 0 | ~15% |
| 200 | 92 | 21 | 0 | 33% |
| 400 | 185 | 30 | 0 | 74% |
| 600, первые 40 с | 270 | 240 | 0 | **97%** |
| 600, дальше | 10–40 | **10 000** | ReadTimeout, 500 | **6%** |

На 600 процесс упирается в одно ядро, а потом происходит странное: RPS и CPU падают, p95 —
10 с (это таймаут запроса в Locust). На вкладке **FAILURES** — `ReadTimeout` и
`500 Server Error`. Запрос из терминала C в этот момент:

```
        state        | count
---------------------+-------
 active              |     1
 idle in transaction |    15
```

Все 15 соединений пула заняты и при этом простаивают. В прошлых замерах на загруженном
ноутбуке развал начинался уже на 400. Если на 600 всё держится, нужно поднять до 800.

## 4. Узкое место и как его нашли (пункт 4)

В Locust — **STOP**. Нагрузки уже нет, а API всё равно не отвечает (терминал C):

```bash
curl -m 10 http://127.0.0.1:8020/menu/items
```

Ответ через 10 с: `curl: (28) Operation timed out after 10001 milliseconds with 0 bytes received`. Запрос `psql` из шага 3 по-прежнему
показывает 15 соединений `idle in transaction`.

Что сказать:

**Узкое место — один процесс API.** Python выполняет код в одном потоке за раз (GIL), поэтому
под нагрузкой процесс упирается в одно ядро: `top` показывает около 100%. Запросы встают
в очередь, и дальше пул соединений с БД (15) и пул потоков FastAPI (40) начинают ждать друг
друга. Соединения заняты запросами, которые ждут свободный поток, а потоки — запросами, которые
ждут соединение. CPU простаивает, API висит.

**Как нашли:** latency и ошибки — в Locust, CPU — в `top`, зависшие соединения — в
`pg_stat_activity`. Кто чего ждёт, показал дамп потоков: 40 из 40 потоков ждут соединение из пула
(`docs/lab10/load/baseline/thread_dump.txt`, снят заранее).

**Как лечится:** 4 процесса API и пул побольше. После этого держит 1600 пользователей без ошибок.
Цифры до и после — `docs/lab10/load/RESULTS.md`.

Grafana из ЛР № 9 здесь не подключена: API запущен процессом на хосте, а не в контейнере.
Метрики те же — CPU, соединения с БД, latency.

### После нагрузки

Ctrl+C в терминалах B (Locust) и A (API), затем:

```bash
scripts/load_stand.sh down
```

Контейнеры остановлены, данные остаются.

## После показа

```bash
git status
```

Ответ: `nothing to commit, working tree clean`. Если `repository.py` из шага 2 остался
изменённым — `git checkout` из этого шага. Контейнеры стенда остановлены в шаге 4.
