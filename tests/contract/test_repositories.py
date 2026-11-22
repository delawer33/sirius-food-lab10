"""
Контрактные тесты: обе реализации каждого репозитория ведут себя одинаково.

Один и тот же набор проверок запускается для SQLAlchemy и для in-memory.
Если тесты зелёные для обеих, сервис может работать с любой из них
(принцип подстановки Лисков).
"""
from datetime import datetime
from types import SimpleNamespace

import pytest

from app.modules.auth.repository import InMemoryAuthRepository, SqlAlchemyAuthRepository
from app.modules.delivery.repository import (
    InMemoryDeliveryRepository,
    SqlAlchemyDeliveryRepository,
)
from app.modules.menu.repository import InMemoryMenuRepository, SqlAlchemyMenuRepository
from app.modules.orders.repository import InMemoryOrderRepository, SqlAlchemyOrderRepository
from app.modules.users.repository import InMemoryUserRepository, SqlAlchemyUserRepository

EXPIRES = datetime(2030, 1, 1)


@pytest.fixture(params=["sql", "memory"])
def repos(request, db_session, storage):
    """Репозитории всех модулей, разделяющие одно хранилище, как в работающем приложении."""
    if request.param == "sql":
        return SimpleNamespace(
            users=SqlAlchemyUserRepository(db_session),
            menu=SqlAlchemyMenuRepository(db_session),
            orders=SqlAlchemyOrderRepository(db_session),
            delivery=SqlAlchemyDeliveryRepository(db_session),
            auth=SqlAlchemyAuthRepository(db_session),
        )
    return SimpleNamespace(
        users=InMemoryUserRepository(storage),
        menu=InMemoryMenuRepository(storage),
        orders=InMemoryOrderRepository(storage),
        delivery=InMemoryDeliveryRepository(storage),
        auth=InMemoryAuthRepository(storage),
    )


def add_user(repos, email="anna@sirius.ru", balance=0.0, role="student"):
    return repos.users.create_user(email, None, balance, False, role, "hash")


def test_user_create_and_lookup(repos):
    created = repos.users.create_user("anna@sirius.ru", "+79990001122", 0.0, False, "student", "h1")
    second = repos.users.create_user("boris@sirius.ru", None, 0.0, False, "cook", "h2")

    assert (created.id, second.id) == (1, 2)
    assert (second.role, second.password_hash, second.token_version) == ("cook", "h2", 0)
    assert repos.users.get_user_by_id(1) == created
    assert repos.users.get_user_by_email("boris@sirius.ru") == second
    assert repos.users.get_user_by_id(999) is None
    assert repos.users.get_user_by_email("nobody@sirius.ru") is None


def test_user_update_balance_role_and_block(repos):
    add_user(repos)

    assert repos.users.update_balance(1, 150.5) == 150.5
    assert repos.users.set_role(1, "courier").role == "courier"
    assert repos.users.set_blocked(1, True).is_blocked is True
    stored = repos.users.get_user_by_id(1)
    assert (stored.balance, stored.role, stored.is_blocked) == (150.5, "courier", True)


def test_changing_returned_entity_does_not_persist(repos):
    add_user(repos)
    repos.menu.create_item("Борщ", 250.0, True)

    repos.users.get_user_by_id(1).balance = 1_000_000
    repos.menu.get_item_by_id(1).price = 1

    assert repos.users.get_user_by_id(1).balance == 0.0
    assert repos.menu.get_item_by_id(1).price == 250.0


def test_menu_create_lookup_and_save(repos):
    item = repos.menu.create_item("Борщ", 250.0, True)
    item.price = 200.0
    item.is_available = False
    repos.menu.save_item(item)
    repos.menu.create_item("Компот", 60.0, True)

    assert repos.menu.get_item_by_name("Борщ") == item
    assert repos.menu.get_item_by_id(1).is_available is False
    assert [i.name for i in repos.menu.list_items()] == ["Борщ", "Компот"]
    assert repos.menu.get_item_by_id(999) is None
    assert repos.menu.get_item_by_name("Плов") is None


def test_order_save_lookup_and_lists(repos):
    add_user(repos, balance=1000.0)
    add_user(repos, email="boris@sirius.ru")
    repos.menu.create_item("Борщ", 200.0, True)

    first = repos.orders.save_order(1, 1, quantity=3, total_cost=600.0, new_balance=400.0)
    second = repos.orders.save_order(1, 1, quantity=1, total_cost=200.0, new_balance=200.0)
    repos.orders.set_order_status(second, "ready")

    assert (first, second) == (1, 2)
    assert repos.orders.get_user_by_id(1).balance == 200.0
    assert repos.orders.get_menu_item_by_id(1).name == "Борщ"
    order = repos.orders.get_order(1)
    assert (order.user_id, order.quantity, order.status, order.total_cost) == (1, 3, "processing", 600.0)
    assert repos.orders.get_order(999) is None
    assert [o.id for o in repos.orders.list_orders_by_user(1)] == [1, 2]
    assert repos.orders.list_orders_by_user(2) == []
    assert [o.id for o in repos.orders.list_orders_by_status("processing")] == [1]


def test_order_cancel_refunds_atomically(repos):
    add_user(repos, balance=1000.0)
    repos.menu.create_item("Борщ", 200.0, True)
    repos.orders.save_order(1, 1, quantity=3, total_cost=600.0, new_balance=400.0)

    cancelled = repos.orders.cancel_order(1, "cancelled", new_balance=1000.0)

    assert cancelled.status == "cancelled"
    assert repos.orders.get_user_by_id(1).balance == 1000.0


def test_delivery_repository_orders_and_users(repos):
    """Доставки теперь в шлюзах (test_delivery_gateways.py), здесь — заказы и курьеры."""
    add_user(repos, balance=1000.0)
    add_user(repos, email="courier@sirius.ru", role="courier")
    repos.menu.create_item("Борщ", 200.0, True)
    repos.orders.save_order(1, 1, quantity=1, total_cost=200.0, new_balance=800.0)

    repos.delivery.set_order_status(1, "delivering")

    assert repos.delivery.get_order(1).status == "delivering"
    assert repos.delivery.get_order(999) is None
    assert repos.delivery.get_user_by_id(2).role == "courier"
    assert repos.delivery.get_user_by_id(999) is None


def test_refresh_token_storage_and_single_use_revoke(repos):
    add_user(repos)
    repos.auth.save_refresh_token(1, "hash-a", EXPIRES)

    token = repos.auth.get_refresh_token("hash-a")

    assert (token.user_id, token.expires_at, token.is_revoked) == (1, EXPIRES, False)
    assert repos.auth.get_refresh_token("unknown") is None
    assert repos.auth.revoke_refresh_token(token.id) is True
    # Второй отзыв того же токена сообщает, что он уже был отозван.
    assert repos.auth.revoke_refresh_token(token.id) is False
    assert repos.auth.get_refresh_token("hash-a").is_revoked is True


def test_revoke_all_sessions(repos):
    add_user(repos)
    add_user(repos, email="boris@sirius.ru")
    repos.auth.save_refresh_token(1, "a1", EXPIRES)
    repos.auth.save_refresh_token(1, "a2", EXPIRES)
    repos.auth.save_refresh_token(2, "b1", EXPIRES)

    repos.auth.revoke_all_sessions(1)

    assert repos.auth.get_refresh_token("a1").is_revoked
    assert repos.auth.get_refresh_token("a2").is_revoked
    assert not repos.auth.get_refresh_token("b1").is_revoked
    assert repos.auth.get_user_by_id(1).token_version == 1
    assert repos.auth.get_user_by_email("boris@sirius.ru").token_version == 0
