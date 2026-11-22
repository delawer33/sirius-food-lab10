"""
Нагрузочный тест «Сириус.Еды»: витрина, карточка блюда, заказ.

    locust -f locustfile.py --host=http://127.0.0.1:8010

Веб-интерфейс: http://localhost:8089. Без интерфейса, ступенями 50 → 100 → 200
пользователей и с записью CSV — scripts/load_steps.sh.

Перед запуском: студенты load1..load20@sirius.ru (scripts/seed_load.py) и
RATE_LIMIT_ENABLED=False у API, иначе заказы упрутся в лимит 10 в минуту
с одного IP: все виртуальные пользователи Locust приходят с одного адреса.
"""
import itertools
import os
import random

from locust import HttpUser, between, events, task

STUDENTS = int(os.getenv("LOAD_STUDENTS", "20"))
PASSWORD = os.getenv("DEMO_PASSWORD", "sirius-demo")
# Без таймаута зависший запрос не попадёт ни в latency, ни в ошибки.
TIMEOUT = 10

tokens: list[str] = []
item_ids: list[int] = []
next_student = itertools.count()


@events.test_start.add_listener
def login_students(environment, **_):
    """
    Токены берутся один раз до нагрузки. Логин — это bcrypt (~0,2 с CPU),
    200 логинов при старте пользователей сами стали бы нагрузкой.
    """
    import requests

    host = environment.host
    tokens.clear()
    for n in range(1, STUDENTS + 1):
        response = requests.post(f"{host}/auth/login", timeout=TIMEOUT,
                                 json={"email": f"load{n}@sirius.ru", "password": PASSWORD})
        response.raise_for_status()
        tokens.append(response.json()["access_token"])
    item_ids[:] = [item["id"] for item in requests.get(f"{host}/menu/items", timeout=TIMEOUT).json()]


class SiriusUser(HttpUser):
    """Студент на большой перемене: смотрит меню, иногда заказывает."""

    wait_time = between(1, 3)

    def on_start(self):
        token = tokens[next(next_student) % len(tokens)]
        self.headers = {"Authorization": f"Bearer {token}"}

    @task(7)
    def get_menu(self):
        """70% запросов — витрина."""
        self.client.get("/menu/items", timeout=TIMEOUT)

    @task(2)
    def get_menu_item(self):
        """20% — карточка блюда."""
        self.client.get(f"/menu/items/{random.choice(item_ids)}", name="/menu/items/[id]", timeout=TIMEOUT)

    @task(1)
    def create_order(self):
        """10% — заказ. Деньги у студентов на демо почти бесконечные."""
        self.client.post("/orders/create", headers=self.headers, timeout=TIMEOUT,
                         json={"item_id": random.choice(item_ids), "quantity": 1})
