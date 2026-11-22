"""
Сквозная проверка API: прогоняет ветки эндпоинтов всех модулей на пустом
хранилище и печатает «запрос -> статус тело».

    python scripts/smoke.py          # SQLAlchemy + временный файл SQLite
    python scripts/smoke.py memory   # in-memory репозитории

Строки с пометкой [mvp] — те же сценарии, что в docs/smoke_mvp.txt (ответы
MVP-версии из лабораторной № 2), только запросы теперь идут с токеном.
Их ответы обязаны совпадать с MVP: для авторизованного пользователя API
не изменилось. Остальные строки — сценарии безопасности. Весь вывод
сравнивается с docs/smoke_lab3.txt в tests/api/test_smoke.py.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Callable

PASSWORD = "smoke-password"
TOKEN_FIELDS = ("access_token", "refresh_token")


def mask(data):
    """Токены случайные: в выводе только факт, что они есть."""
    if isinstance(data, dict):
        return {k: "<jwt>" if k in TOKEN_FIELDS else v for k, v in data.items()}
    return data


def run(client, create_staff: Callable[[str, str], None]) -> list[str]:
    """create_staff(email, role) создаёт сотрудника в обход API — как CLI-скрипт."""
    lines = []
    tokens: dict[str, dict] = {}

    def call(method: str, url: str, as_user: str | None = None, mvp: bool = False, **kwargs):
        headers = kwargs.pop("headers", {})
        if as_user:
            headers["Authorization"] = f"Bearer {tokens[as_user]['access_token']}"
        response = client.request(method, url, headers=headers, **kwargs)
        data = response.json()
        body = json.dumps(mask(data), ensure_ascii=False, sort_keys=True)
        who = f" as {as_user}" if as_user else ""
        tag = "[mvp] " if mvp else ""
        lines.append(f"{tag}{method} {url}{who} {mask(kwargs.get('json', ''))} -> {response.status_code} {body}")
        return data

    def login(name: str, email: str) -> None:
        tokens[name] = call("POST", "/auth/login", json={"email": email, "password": PASSWORD})

    # users: регистрация теперь с паролем
    call("POST", "/users/register", mvp=True, json={"email": "anna@sirius.ru", "password": PASSWORD, "phone": "+79990001122"})
    call("POST", "/users/register", mvp=True, json={"email": "anna@sirius.ru", "password": PASSWORD})
    call("POST", "/users/register", mvp=True, json={"email": "boris@sirius.ru", "password": PASSWORD, "phone": "123"})
    call("POST", "/users/register", mvp=True, json={"email": "boris@sirius.ru", "password": PASSWORD})
    call("POST", "/users/register", mvp=True, json={"email": "not-an-email", "password": PASSWORD})
    call("POST", "/users/register", json={"email": "short@sirius.ru", "password": "1234567"})

    create_staff("admin@sirius.ru", "admin")      # id 3
    create_staff("cook@sirius.ru", "cook")        # id 4
    create_staff("courier@sirius.ru", "courier")  # id 5
    login("anna", "anna@sirius.ru")
    login("boris", "boris@sirius.ru")
    login("admin", "admin@sirius.ru")
    login("cook", "cook@sirius.ru")
    login("courier", "courier@sirius.ru")
    call("POST", "/auth/login", json={"email": "anna@sirius.ru", "password": "wrong-password"})
    call("POST", "/auth/login", json={"email": "nobody@sirius.ru", "password": PASSWORD})
    call("GET", "/users/me", as_user="anna")

    call("POST", "/users/1/topup?amount=0", as_user="anna", mvp=True)
    call("POST", "/users/999/topup?amount=100", as_user="admin", mvp=True)
    call("POST", "/users/999/topup?amount=100", as_user="anna")
    call("POST", "/users/1/topup?amount=50001", as_user="anna", mvp=True)
    call("POST", "/users/1/topup?amount=1000", as_user="anna", mvp=True)
    call("PATCH", "/users/2/block", as_user="anna", json={"is_blocked": True})
    call("PATCH", "/users/2/block", as_user="admin", json={"is_blocked": True})
    call("POST", "/users/2/topup?amount=100", as_user="admin", mvp=True)
    call("GET", "/users/me", as_user="boris")

    # menu: меняют только повар и администратор
    call("POST", "/menu/items", as_user="anna", json={"name": "Борщ", "price": 250})
    call("POST", "/menu/items", as_user="cook", mvp=True, json={"name": "Борщ", "price": 250})
    call("POST", "/menu/items", as_user="cook", mvp=True, json={"name": "Борщ", "price": 300})
    call("POST", "/menu/items", as_user="cook", mvp=True, json={"name": "Плов", "price": 0})
    call("POST", "/menu/items", as_user="cook", mvp=True, json={"name": "П", "price": 100})
    call("POST", "/menu/items", as_user="admin", mvp=True, json={"name": "Компот", "price": 60})
    call("PATCH", "/menu/items/999", as_user="cook", mvp=True, json={"price": 10})
    call("PATCH", "/menu/items/1", as_user="cook", mvp=True, json={"price": -5})
    call("PATCH", "/menu/items/1", as_user="cook", mvp=True, json={"price": 200})
    call("PATCH", "/menu/items/2", as_user="cook", mvp=True, json={"is_available": False})
    call("PATCH", "/menu/items/2", as_user="cook", mvp=True, json={"name": "Компот вишнёвый"})
    call("PATCH", "/menu/items/1", as_user="courier", json={"price": 1})
    call("GET", "/menu/items")

    # orders: user_id больше не передаётся, он берётся из токена
    call("POST", "/orders/create", json={"item_id": 1, "quantity": 1})
    call("POST", "/orders/create", headers={"Authorization": "Bearer garbage"}, json={"item_id": 1, "quantity": 1})
    call("POST", "/orders/create", headers={"Authorization": f"Bearer {tokens['anna']['refresh_token']}"}, json={"item_id": 1, "quantity": 1})
    call("POST", "/orders/create", as_user="cook", json={"item_id": 1, "quantity": 1})
    call("POST", "/orders/create", as_user="anna", mvp=True, json={"item_id": 1, "quantity": 0})
    call("POST", "/orders/create", as_user="anna", mvp=True, json={"item_id": 999, "quantity": 1})
    call("POST", "/orders/create", as_user="anna", mvp=True, json={"item_id": 2, "quantity": 1})
    call("POST", "/orders/create", as_user="anna", mvp=True, json={"item_id": 1, "quantity": 10})
    call("POST", "/orders/create", as_user="anna", mvp=True, json={"item_id": 1, "quantity": 3})
    call("POST", "/users/1/topup?amount=1", as_user="anna", mvp=True)  # 1000 - 3*200 = 400, после пополнения 401
    # user_id в теле игнорируется: заказ всё равно оформляется на владельца токена.
    call("POST", "/orders/create", as_user="anna", json={"user_id": 2, "item_id": 1, "quantity": 1})

    # IDOR: второй студент и чужие заказы
    call("PATCH", "/users/2/block", as_user="admin", json={"is_blocked": False})
    call("POST", "/users/1/topup?amount=500", as_user="boris")
    call("POST", "/users/2/topup?amount=500", as_user="boris")
    call("POST", "/orders/create", as_user="boris", json={"item_id": 1, "quantity": 1})
    call("GET", "/orders/3", as_user="anna")
    call("POST", "/orders/3/cancel", as_user="anna")
    call("GET", "/orders/3", as_user="cook")
    call("POST", "/orders/3/cancel", as_user="boris")
    call("POST", "/orders/3/cancel", as_user="boris")
    call("POST", "/orders/999/cancel", as_user="boris")
    call("GET", "/orders/my", as_user="boris")
    call("GET", "/users/me", as_user="boris")

    # kitchen: только повар и администратор
    call("GET", "/kitchen/orders", as_user="anna")
    call("GET", "/kitchen/orders", as_user="cook")
    call("POST", "/delivery/assign", as_user="admin", json={"order_id": 1, "courier_id": 5})
    call("POST", "/kitchen/orders/1/ready", as_user="courier")
    call("POST", "/kitchen/orders/1/ready", as_user="cook")
    call("POST", "/orders/1/cancel", as_user="anna")

    # delivery: курьер видит только свои доставки
    call("POST", "/delivery/assign", as_user="courier", json={"order_id": 1, "courier_id": 5})
    call("POST", "/delivery/assign", as_user="admin", json={"order_id": 1, "courier_id": 2})
    call("POST", "/delivery/assign", as_user="admin", json={"order_id": 1, "courier_id": 5})
    call("POST", "/delivery/assign", as_user="admin", json={"order_id": 1, "courier_id": 5})
    call("GET", "/delivery/my", as_user="courier")
    call("GET", "/delivery/my", as_user="anna")
    call("GET", "/delivery/1", as_user="boris")
    call("GET", "/delivery/1", as_user="anna")
    call("PATCH", "/delivery/1/complete", as_user="anna")
    call("PATCH", "/delivery/1/complete", as_user="courier")
    call("PATCH", "/delivery/1/complete", as_user="courier")
    call("GET", "/orders/1", as_user="anna")

    # роли назначает администратор
    call("PATCH", "/users/2/role", as_user="boris", json={"role": "admin"})
    call("PATCH", "/users/3/role", as_user="admin", json={"role": "student"})
    call("PATCH", "/users/2/role", as_user="admin", json={"role": "superuser"})
    call("PATCH", "/users/2/role", as_user="admin", json={"role": "courier"})
    call("GET", "/delivery/my", as_user="boris")

    # Refresh Token rotation
    old = tokens["anna"]
    login("anna", "anna@sirius.ru")
    new = call("POST", "/auth/refresh", json={"refresh_token": old["refresh_token"]})
    call("POST", "/auth/refresh", json={"refresh_token": old["access_token"]})
    call("GET", "/users/me", headers={"Authorization": f"Bearer {new['access_token']}"})
    # Старый refresh-токен предъявлен второй раз: его украли, все сессии сбрасываются.
    call("POST", "/auth/refresh", json={"refresh_token": old["refresh_token"]})
    call("POST", "/auth/refresh", json={"refresh_token": new["refresh_token"]})
    call("POST", "/auth/refresh", json={"refresh_token": tokens["anna"]["refresh_token"]})
    call("GET", "/users/me", headers={"Authorization": f"Bearer {new['access_token']}"})
    login("anna", "anna@sirius.ru")
    call("GET", "/users/me", as_user="anna")
    call("POST", "/auth/logout", json={"refresh_token": tokens["anna"]["refresh_token"]})
    call("POST", "/auth/refresh", json={"refresh_token": tokens["anna"]["refresh_token"]})
    return lines


def main() -> None:
    backend = sys.argv[1] if len(sys.argv) > 1 else "sql"
    db_file = Path(tempfile.mkdtemp()) / "smoke.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_file}"
    os.environ["REPO_BACKEND"] = backend
    os.environ["RATE_LIMIT_ENABLED"] = "false"
    os.environ.setdefault("SECRET_KEY", "smoke-secret-key-that-is-long-enough-for-hs256")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from fastapi.testclient import TestClient

    from app import container
    from app.database import Base, SessionLocal, engine
    from app.main import app
    from app.models import seed_roles
    from app.modules.users.repository import InMemoryUserRepository, SqlAlchemyUserRepository
    from app.modules.users.service import UserService

    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        seed_roles(session)

    def create_staff(email: str, role: str) -> None:
        if backend == "memory":
            UserService(InMemoryUserRepository(container.memory_storage)).create_user(email, PASSWORD, role)
        else:
            with SessionLocal() as session:
                UserService(SqlAlchemyUserRepository(session)).create_user(email, PASSWORD, role)

    print("\n".join(run(TestClient(app), create_staff)))


if __name__ == "__main__":
    main()
