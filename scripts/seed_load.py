"""
Данные для нагрузочного теста: демо-меню и студенты load1..loadN@sirius.ru
с 10 млн на балансе. Повторный запуск дублей не создаёт.

    python -m scripts.seed_load            # 20 студентов
    LOAD_STUDENTS=50 python -m scripts.seed_load
"""
import os

from app.database import SessionLocal
from app.modules.users.repository import SqlAlchemyUserRepository
from app.modules.users.service import UserService
from scripts import seed_demo


def main() -> None:
    seed_demo.main()
    count = int(os.getenv("LOAD_STUDENTS", "20"))
    password = os.getenv("DEMO_PASSWORD", "sirius-demo")
    with SessionLocal() as session:
        users = UserService(SqlAlchemyUserRepository(session))
        for n in range(1, count + 1):
            email = f"load{n}@sirius.ru"
            if users.repository.get_user_by_email(email) is None:
                user = users.create_user(email, password, "student")
                users.repository.update_balance(user.id, 10_000_000.0)
    print(f"Студентов для нагрузки: {count}")


if __name__ == "__main__":
    main()
