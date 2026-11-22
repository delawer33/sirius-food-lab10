"""
Демо-данные для проверки в Swagger: по пользователю на каждую роль,
второй студент для проверки IDOR, два блюда в меню, курьер на смене.

    python -m scripts.seed_demo

Только для локальной БД: у всех демо-пользователей один пароль
(DEMO_PASSWORD, по умолчанию sirius-demo).
"""
import os

from app.database import SessionLocal
from delivery_service.storage import CourierShiftRow
from app.modules.menu.repository import SqlAlchemyMenuRepository
from app.modules.menu.service import MenuService
from app.modules.users.repository import SqlAlchemyUserRepository
from app.modules.users.service import UserService

DEMO_USERS = [
    # Телефон у студентов — чтобы после заказа уходило SMS (лабораторная № 5).
    ("student@sirius.ru", "student", 10_000_000.0, "+79990000001"),
    ("student2@sirius.ru", "student", 10_000_000.0, "+79990000002"),
    ("cook@sirius.ru", "cook", 0.0, None),
    ("courier@sirius.ru", "courier", 0.0, None),
    ("admin@sirius.ru", "admin", 0.0, None),
]
# Борщ и Компот — первыми: на их id завязаны демо прошлых лаб. Остальное — витрина ЛР № 8.
DEMO_MENU = [
    ("Борщ", 250.0),
    ("Компот", 60.0),
    ("Сырники", 150.0),
    ("Плов с бараниной", 320.0),
    ("Цезарь с курицей", 290.0),
    ("Блины со сметаной", 180.0),
    ("Пельмени домашние", 270.0),
    ("Морс клюквенный", 90.0),
]


def main() -> None:
    password = os.getenv("DEMO_PASSWORD", "sirius-demo")
    with SessionLocal() as session:
        users = UserService(SqlAlchemyUserRepository(session))
        for email, role, balance, phone in DEMO_USERS:
            if users.repository.get_user_by_email(email):
                continue
            user = users.create_user(email, password, role, phone)
            if balance:
                users.repository.update_balance(user.id, balance)
            print(f"{role:8} {email:20} id {user.id}")

        # Сервис доставки знает, кто из курьеров на смене (лабораторная № 7).
        for email, role, *_ in DEMO_USERS:
            courier = users.repository.get_user_by_email(email)
            if role == "courier" and session.get(CourierShiftRow, courier.id) is None:
                session.add(CourierShiftRow(courier_id=courier.id, on_shift=True))
                print(f"courier  {email:20} на смене")
        session.commit()

        menu = MenuService(SqlAlchemyMenuRepository(session))
        for name, price in DEMO_MENU:
            if not menu.repository.get_item_by_name(name):
                menu.create_item(name, price)
    print(f"Пароль у всех: {password}")


if __name__ == "__main__":
    main()
