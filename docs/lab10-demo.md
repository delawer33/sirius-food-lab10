# ЛР № 10 руками: как показать

Порядок — как в разделе «Что сдавать» методички. Только стандартные инструменты: `pytest`,
`docker`, `psql`, `curl`, `top`, `grep`, веб-интерфейс Locust, страницы GitHub и `gh`.
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
`tee` пишет вывод API ещё и в файл: он понадобится в шаге 4.

```bash
scripts/load_stand.sh up
```
```bash
WORKERS=1 scripts/load_stand.sh api 2>&1 | tee /tmp/lab10-api.log
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

В Locust — **STOP**. Нагрузки нет, но API не отвечает (терминал C):

```bash
curl -s -m 10 -o /dev/null -w '%{http_code} %{time_total}\n' http://127.0.0.1:8020/menu/items
```

Ответ: `000 10.00…` — за 10 с ни одного байта. `psql` из шага 3 по-прежнему показывает
15 соединений `idle in transaction`.

Смотрим, на чём стоят потоки. Стенд запускает API с `PYTHONFAULTHANDLER=1`, по сигналу
6 (SIGABRT) Python печатает стеки всех потоков и завершается. В zsh `kill -ABRT` не работает
(там этот сигнал называется IOT), поэтому номер:

```bash
kill -6 $(pgrep -f 'python -m uvicorn app.main:app')
```

В терминале A печатаются стеки, они же в `/tmp/lab10-api.log`. Посчитать:

```bash
grep -c '^Thread 0x' /tmp/lab10-api.log
```
```bash
grep -c 'util/queue.py", line 201 in get' /tmp/lab10-api.log
```
```bash
grep -c 'router.py", line 39 in get_menu_item' /tmp/lab10-api.log
```
```bash
grep -c 'QueuePool limit of size 5 overflow 10 reached' /tmp/lab10-api.log
```

Ответы на этом прогоне: 50 потоков. 40 из них ждут соединение из пула SQLAlchemy
(`sqlalchemy/util/queue.py`), все 40 — в `GET /menu/items/{id}`: карточка блюда не кешируется,
в отличие от витрины. Ответов 500 «QueuePool limit … reached» — 208.

Что произошло:

1. Один процесс API, Python исполняет код в одном потоке за раз (GIL). На 600 пользователях
   процессор занят целиком, запросы встают в очередь.
2. Синхронные обработчики FastAPI работают в пуле из 40 потоков, а у SQLAlchemy 15 соединений
   (5 + 10) с ожиданием 30 с.
3. Соединения держат запросы, которые уже сходили в базу и ждут свободный поток, чтобы
   продолжить. Потоки заняты запросами, которые ждут соединение. Получается взаимное
   ожидание: соединения `idle in transaction`, CPU простаивает. Через 30 с ожидание
   обрывается ошибкой 500, но очередь тут же занимает потоки снова.

**Узкое место: один процесс API, пул соединений меньше пула потоков, ожидание соединения 30 с.**

Почему не Grafana. Grafana из ЛР № 9 смотрит на контейнер `app` из compose, а здесь API —
процесс на хосте, чтобы менять число воркеров и пул. Метрики те же: CPU (`top`), соединения
с БД (`pg_stat_activity`), latency (Locust). Дамп потоков показал то, чего на графиках нет:
кто и чего ждёт.

### Исправление

Четыре процесса API и пул под них: 10 + 10 соединений на процесс, ожидание соединения 3 с.
Это настройки окружения, код не меняется (`app/core/config.py`, `DB_POOL_*`). Процесс API
из шага 4 уже завершён. Терминал A:

```bash
WORKERS=4 DB_POOL_SIZE=10 DB_MAX_OVERFLOW=10 DB_POOL_TIMEOUT=3 scripts/load_stand.sh api 2>&1 | tee /tmp/lab10-api.log
```

В Locust — **NEW**, Number of users `600`, Ramp up `10`, **START**. Через полторы минуты:

| Пользователи | RPS | p95, мс | Ошибки | CPU API |
|---|---|---|---|---|
| 600 | 190 | 19 | 0 | 4 процесса по ~23% |

`top` из шага 3 теперь показывает 4 процесса `multiprocessing.spawn`: работа поделена
на ядра, у каждого процесса свой GIL. 4 × 20 = 80 соединений, лимит PostgreSQL — 100.
Короткое ожидание — страховка: если пул всё же кончится, запрос быстро получит ошибку
и освободит поток.

Предел новой конфигурации — около 1600 пользователей (RPS 360, p95 390 мс): таблица в README,
раздел «Нагрузка», сырые CSV — `docs/lab10/load/`.

### После нагрузки

Ctrl+C в терминалах B (Locust) и A (API), затем:

```bash
scripts/load_stand.sh down
```

Контейнеры остановлены, данные остаются.

## 5. CI в GitHub Actions (пункт 5)

Репозиторий: https://github.com/delawer33/sirius-food-lab10

- **Зелёный на пуш.** Вкладка [Actions](https://github.com/delawer33/sirius-food-lab10/actions),
  workflow `Tests`: прогоны на `main` с зелёной галочкой. Внутри — шаги «Run unit and API tests»
  (361 тест) и «Run integration tests» (Testcontainers поднимает PostgreSQL прямо в CI).
  Конфигурация — `.github/workflows/test.yml`.
- **Красный на сломанном тесте.**
  [PR #2](https://github.com/delawer33/sirius-food-lab10/pull/2) «Демо: сломанный тест»
  добавляет в `tests/unit/test_order_service.py` тест с `assert 1 == 2`. Проверка `test`
  красная. Внизу PR (под аккаунтом владельца) кнопка мержа неактивна: обязательная проверка
  не прошла.
- **Почему мерж запрещён.** Settings → Branches → правило для `main`: обязательная проверка
  `test`, правило действует и на владельца.

То же из терминала:

```bash
gh pr checks 2
```
```bash
gh pr view 2 --json mergeStateStatus
```

Ответы: `test	fail …` и `{"mergeStateStatus":"BLOCKED"}`.

## 6. Pact: контракт кухни и монолита (пункт 6, 9–10 баллов)

```bash
pytest tests/pact -v
```

Ответ: `3 passed`. Два consumer-теста кухни пишут контракт, provider-тест монолита его
проверяет. Что кухня требует от событий:

```bash
jq -c '.interactions[] | {description, body: .contents.content}' pacts/kitchen-monolith.json
```

Ответ:

```
{"description":"OrderCancelled","body":{"event_id":"…","event_type":"OrderCancelled","order_id":42,"reason":"client"}}
{"description":"OrderPaid","body":{"event_id":"…","event_type":"OrderPaid","order_id":42}}
```

Это те поля, которые реально читает `kitchen_consumer`. `total` и `currency` из методички
в событии нет, поэтому поломку показываем на `order_id`.

**Сломать контракт.** Открыть `app/domain/events.py`, строка 36, и переименовать
`order_id=order_id` в `orderId=order_id`:

```python
    return _event(ORDER_PAID, "OrderPaid", orderId=order_id, customer_id=customer_id, amount=amount)
```

```bash
pytest tests/pact/test_monolith_provider.py
```

Ответ: `1 failed`, в выводе `Actual map is missing the following keys: order_id`.
Монолит перестал отдавать поле, которое нужно кухне, и тест упал до продакшена. Вернуть:

```bash
git checkout app/domain/events.py
```

## 7. mutmut: слабые тесты (пункт 6, 9–10 баллов)

Настройка — `setup.cfg`, раздел `[mutmut]`: мутируется `app/`, тесты — `tests/unit/`,
только бизнес-логика (сервисы модулей и `app/domain`).

```bash
mutmut run
```

Ответ: `557/557  🎉 468 … 🙁 89`: 468 мутантов убито, 89 выжило. Результаты кешируются
в `mutants/`, повторный запуск — секунды.

Как было до дописанных тестов (сохранённый вывод `mutmut results` первого прогона):

```bash
grep -c survived docs/lab10/mutmut_before.txt
```
```bash
grep -c "no tests" docs/lab10/mutmut_before.txt
```

Ответы: 165 выживших и 21 мутант без тестов. Стало 89 и 0.

Пример убитого мутанта — граница баланса:

```bash
mutmut show 'app.modules.orders.service.xǁOrderServiceǁcreate_order__mutmut_22'
```

Ответ: `killed`, в диффе `balance < total_cost` заменено на `balance <= total_cost`. Раньше
он выживал: студент с ровно 200 ₽ не смог бы заказать блюдо за 200 ₽, а тесты бы молчали.
Его убивает `test_balance_exactly_equal_to_total_is_enough` (`tests/unit/test_order_service.py:165`).
Остальные дописанные тесты помечены комментарием «Добавлено по итогам mutmut», список —
в README, раздел «mutmut: что нашёл».

Кто выжил:

```bash
mutmut results
```

Почти все выжившие меняют только текст ошибки:

```bash
mutmut show 'app.modules.delivery.service.xǁDeliveryServiceǁassign_courier__mutmut_5'
```

Ответ: `"Заказ не найден"` → `"XXЗаказ не найденXX"`. Из 89 таких 84. Проверять каждую
формулировку — значит закрепить текст, а не поведение. Разбор всех 89 —
`docs/lab10/survivors_after.txt`.

## После показа

```bash
git status
```

Ответ: `nothing to commit, working tree clean`. Если файлы из шагов 2 и 6 остались
изменёнными — `git checkout` из этих шагов. Контейнеры стенда остановлены в шаге 4.
