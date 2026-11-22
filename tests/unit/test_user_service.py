"""
Unit-тесты UserService без СУБД.
"""
import pytest

from app.core.security import verify_password
from app.domain.entities import User
from app.domain.errors import AccessDeniedError, BusinessRuleError, NotFoundError
from app.modules.users.repository import InMemoryUserRepository
from app.modules.users.service import UserService

ADMIN = User(10, "admin@sirius.ru", None, 0.0, False, "admin")


@pytest.fixture
def service(storage):
    return UserService(InMemoryUserRepository(storage))


def add_user(storage, balance=0.0, is_blocked=False, user_id=1, role="student"):
    user = User(user_id, f"user{user_id}@sirius.ru", None, balance, is_blocked, role)
    storage.users[user_id] = user
    return user


def test_register_creates_student_with_zero_balance(service):
    user = service.register("anna@sirius.ru", "secret-password", "+79990001122")

    assert (user.id, user.balance, user.is_blocked, user.role) == (1, 0.0, False, "student")


def test_register_stores_bcrypt_hash_not_password(service, storage):
    service.register("anna@sirius.ru", "secret-password")

    stored = storage.users[1].password_hash
    assert stored.startswith("$2b$") and "secret-password" not in stored
    assert verify_password("secret-password", stored)
    assert not verify_password("wrong-password", stored)


def test_register_rejects_duplicate_email(service, storage):
    storage.users[1] = User(1, "anna@sirius.ru", None, 0.0, False)

    with pytest.raises(BusinessRuleError, match="уже зарегистрирован"):
        service.register("anna@sirius.ru", "secret-password")


def test_create_user_rejects_unknown_role(service):
    with pytest.raises(BusinessRuleError, match="Неизвестная роль"):
        service.create_user("x@sirius.ru", "secret-password", role="root")


def test_top_up_own_balance(service, storage):
    anna = add_user(storage, balance=100.0)

    assert service.top_up(1, 50000, actor=anna) == 50100.0
    assert storage.users[1].balance == 50100.0


def test_top_up_foreign_balance_is_denied(service, storage):
    add_user(storage)
    boris = add_user(storage, user_id=2)

    with pytest.raises(AccessDeniedError, match="чужой баланс"):
        service.top_up(1, 100, actor=boris)
    assert storage.users[1].balance == 0.0


def test_top_up_access_checked_before_existence(service, storage):
    boris = add_user(storage, user_id=2)

    # Студент не узнаёт, существует ли пользователь 999.
    with pytest.raises(AccessDeniedError):
        service.top_up(999, 100, actor=boris)


def test_admin_tops_up_any_balance(service, storage):
    add_user(storage)

    assert service.top_up(1, 100, actor=ADMIN) == 100.0


def test_top_up_unknown_user(service):
    with pytest.raises(NotFoundError):
        service.top_up(1, 100, actor=ADMIN)


def test_top_up_blocked_user_is_denied(service, storage):
    add_user(storage, is_blocked=True)

    with pytest.raises(AccessDeniedError, match="заблокирован"):
        service.top_up(1, 100, actor=ADMIN)


def test_top_up_over_limit_is_rejected(service, storage):
    anna = add_user(storage)

    with pytest.raises(BusinessRuleError, match="50000"):
        service.top_up(1, 50000.01, actor=anna)


def test_change_role(service, storage):
    add_user(storage)

    assert service.change_role(1, "cook", actor=ADMIN).role == "cook"


def test_admin_cannot_change_own_role(service, storage):
    storage.users[10] = ADMIN

    with pytest.raises(BusinessRuleError, match="собственную роль"):
        service.change_role(10, "student", actor=ADMIN)


def test_block_and_unblock(service, storage):
    add_user(storage)

    assert service.set_blocked(1, True, actor=ADMIN).is_blocked is True
    assert service.set_blocked(1, False, actor=ADMIN).is_blocked is False


def test_block_unknown_user(service):
    with pytest.raises(NotFoundError):
        service.set_blocked(1, True, actor=ADMIN)


# --- Добавлено по итогам mutmut (ЛР № 10) ------------------------------------

def test_register_saves_email_and_phone(service, storage):
    """Мутанты email=None и phone=None: тест на регистрацию смотрел только id и баланс."""
    user = service.register("anna@sirius.ru", "secret-password", "+79990001122")

    assert (storage.users[user.id].email, storage.users[user.id].phone) == ("anna@sirius.ru", "+79990001122")
