"""
Создание пользователя с любой ролью из консоли. Так появляется первый
администратор: через API можно зарегистрироваться только студентом.

    python -m scripts.create_user admin@sirius.ru --role admin

Пароль спрашивается интерактивно и не попадает в историю shell.
"""
import argparse
import getpass

from app.database import SessionLocal
from app.domain.errors import DomainError
from app.domain.roles import ALL_ROLES
from app.modules.users.repository import SqlAlchemyUserRepository
from app.modules.users.service import UserService


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("email")
    parser.add_argument("--role", choices=ALL_ROLES, default="student")
    args = parser.parse_args()

    password = getpass.getpass("Пароль (не короче 8 символов): ")
    if len(password) < 8:
        raise SystemExit("Пароль короче 8 символов")
    if password != getpass.getpass("Повторите пароль: "):
        raise SystemExit("Пароли не совпадают")

    with SessionLocal() as session:
        try:
            user = UserService(SqlAlchemyUserRepository(session)).create_user(
                args.email, password, args.role
            )
        except DomainError as error:
            raise SystemExit(error.message)
    print(f"Создан пользователь {user.email}, id {user.id}, роль {user.role}")


if __name__ == "__main__":
    main()
