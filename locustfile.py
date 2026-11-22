"""
Нагрузочный тест меню: обеденный перерыв, все открывают меню одновременно.

    locust -f locustfile.py --host=http://127.0.0.1:8000

Веб-интерфейс: http://localhost:8089, 500 пользователей, spawn rate 10.
Без интерфейса и с записью результатов — scripts/bench.py.
GET /menu/items открыт без входа, токен не нужен.
"""
from locust import HttpUser, between, task


class MenuUser(HttpUser):
    wait_time = between(0.1, 0.5)

    @task
    def get_menu(self):
        self.client.get("/menu/items")
