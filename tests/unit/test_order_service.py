"""
Unit-тесты OrderService. СУБД не нужна: сервис получает in-memory репозиторий.
"""
import pytest

from app.domain.entities import MenuItem, Order, User
from app.domain.errors import AccessDeniedError, BusinessRuleError, NotFoundError
from app.modules.orders.repository import InMemoryOrderRepository
from app.modules.orders.service import OrderService
from tests.fakes import RecordingNotifier

ANNA = User(1, "anna@sirius.ru", None, 0.0, False, "student")
BORIS = User(2, "boris@sirius.ru", None, 0.0, False, "student")
COOK = User(3, "cook@sirius.ru", None, 0.0, False, "cook")
COURIER = User(4, "courier@sirius.ru", None, 0.0, False, "courier")
ADMIN = User(5, "admin@sirius.ru", None, 0.0, False, "admin")


@pytest.fixture
def notifier():
    return RecordingNotifier()


@pytest.fixture
def seed(storage, notifier):
    def _seed(balance=1000.0, price=200.0, is_available=True, user=True, item=True):
        if user:
            storage.users[1] = User(1, "anna@sirius.ru", None, balance, False)
        if item:
            storage.menu_items[1] = MenuItem(1, "Борщ", price, is_available)
        return OrderService(InMemoryOrderRepository(storage), notifier)

    return _seed


@pytest.fixture
def placed(storage, notifier):
    """У Анны оформлен заказ 1 на 600 ₽, на балансе осталось 400 ₽."""
    storage.users[1] = User(1, "anna@sirius.ru", None, 400.0, False)
    storage.orders[1] = Order(1, 1, 1, 3, "processing", 600.0)
    return OrderService(InMemoryOrderRepository(storage), notifier)


def test_create_order_charges_balance_and_saves_order(seed, storage):
    order_id = seed(balance=1000.0, price=200.0).create_order(user_id=1, item_id=1, quantity=3)

    assert order_id == 1
    assert storage.orders[1].status == "processing"
    assert storage.orders[1].total_cost == 600.0
    assert storage.users[1].balance == 400.0


def test_unknown_user_is_not_found(seed):
    with pytest.raises(NotFoundError, match="Пользователь не найден"):
        seed(user=False).create_order(user_id=1, item_id=1, quantity=1)


def test_unknown_item_is_not_found(seed):
    with pytest.raises(NotFoundError, match="Блюдо не найдено"):
        seed(item=False).create_order(user_id=1, item_id=1, quantity=1)


def test_unavailable_item_cannot_be_ordered(seed):
    with pytest.raises(BusinessRuleError, match="Блюдо недоступно"):
        seed(is_available=False).create_order(user_id=1, item_id=1, quantity=1)


def test_insufficient_balance_rejects_order_without_saving(seed, storage):
    with pytest.raises(BusinessRuleError, match="Недостаточно средств"):
        seed(balance=100.0, price=200.0).create_order(user_id=1, item_id=1, quantity=1)

    assert storage.orders == {}
    assert storage.users[1].balance == 100.0


def test_owner_cancels_order_and_gets_refund(placed, storage):
    placed.cancel_order(1, actor=ANNA)

    assert storage.orders[1].status == "cancelled"
    assert storage.users[1].balance == 1000.0


def test_cannot_cancel_foreign_order(placed, storage):
    """IDOR: студент Б не может отменить заказ студента А."""
    with pytest.raises(AccessDeniedError, match="чужой заказ"):
        placed.cancel_order(1, actor=BORIS)

    assert storage.orders[1].status == "processing"
    assert storage.users[1].balance == 400.0


def test_admin_cancels_any_order(placed, storage):
    placed.cancel_order(1, actor=ADMIN)

    assert storage.users[1].balance == 1000.0


def test_cannot_cancel_order_after_kitchen(placed, storage):
    storage.orders[1].status = "ready"

    with pytest.raises(BusinessRuleError, match="ещё готовится"):
        placed.cancel_order(1, actor=ANNA)


def test_cancel_unknown_order(placed):
    with pytest.raises(NotFoundError, match="Заказ не найден"):
        placed.cancel_order(999, actor=ANNA)


@pytest.mark.parametrize("actor", [ANNA, COOK, ADMIN])
def test_order_visible_to_owner_and_staff(placed, actor):
    assert placed.get_order(1, actor=actor).id == 1


@pytest.mark.parametrize("actor", [BORIS, COURIER])
def test_order_hidden_from_others(placed, actor):
    with pytest.raises(AccessDeniedError):
        placed.get_order(1, actor=actor)


def test_list_my_orders_returns_only_own(placed, storage):
    storage.orders[2] = Order(2, 2, 1, 1, "processing", 200.0)

    assert [o.id for o in placed.list_my_orders(ANNA)] == [1]
    assert [o.id for o in placed.list_my_orders(BORIS)] == [2]


def test_kitchen_sees_processing_orders_and_marks_ready(placed, storage):
    storage.orders[2] = Order(2, 1, 1, 1, "cancelled", 200.0)

    assert [o.id for o in placed.get_kitchen_orders()] == [1]
    placed.mark_ready(1)
    assert storage.orders[1].status == "ready"
    assert placed.get_kitchen_orders() == []


def test_mark_ready_only_from_processing(placed, storage):
    storage.orders[1].status = "cancelled"

    with pytest.raises(BusinessRuleError):
        placed.mark_ready(1)


# --- Фоновые задачи после оформления заказа ----------------------------------

def test_order_created_triggers_notifications(seed, storage, notifier):
    storage.users[1] = User(1, "anna@sirius.ru", "+79990001122", 1000.0, False)
    service = seed(user=False)

    order_id = service.create_order(user_id=1, item_id=1, quantity=1)

    assert notifier.calls == [(order_id, "anna@sirius.ru", "+79990001122")]


def test_rejected_order_triggers_nothing(seed, notifier):
    with pytest.raises(BusinessRuleError):
        seed(balance=10.0).create_order(user_id=1, item_id=1, quantity=1)

    assert notifier.calls == []
