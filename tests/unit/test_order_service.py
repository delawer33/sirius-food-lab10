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


# --- Добавлено по итогам mutmut (ЛР № 10) ------------------------------------
# Каждый тест убивает мутанта, который выживал: код ломался, а тесты молчали.

def test_balance_exactly_equal_to_total_is_enough(seed, storage):
    """Мутант `balance < total` → `balance <= total`: последние 200 ₽ на заказ за 200 ₽."""
    seed(balance=200.0, price=200.0).create_order(user_id=1, item_id=1, quantity=1)

    assert storage.users[1].balance == 0.0


def test_order_saved_with_requested_item_and_quantity(seed, storage):
    """Мутанты item_id=None, quantity=None при сохранении заказа."""
    storage.menu_items[7] = MenuItem(7, "Компот", 60.0, True)
    order_id = seed().create_order(user_id=1, item_id=7, quantity=3)

    order = storage.orders[order_id]
    assert (order.user_id, order.item_id, order.quantity, order.total_cost) == (1, 7, 3, 180.0)


def test_order_paid_event_goes_to_outbox(seed, storage):
    """Мутанты: событие не создаётся, в нём None вместо id заказа, клиента или суммы."""
    order_id = seed(price=200.0).create_order(user_id=1, item_id=1, quantity=2)

    [event] = storage.outbox
    assert event.routing_key == "order.paid"
    assert event.payload["event_type"] == "OrderPaid"
    assert (event.payload["order_id"], event.payload["customer_id"], event.payload["amount"]) == (order_id, 1, 400.0)


def test_cancel_publishes_order_cancelled_with_refund(placed, storage):
    """Мутанты: событие отмены пропадает или теряет id, клиента, сумму, причину."""
    placed.cancel_order(1, actor=ANNA)

    [event] = storage.outbox
    assert event.routing_key == "order.cancelled"
    assert {k: event.payload[k] for k in ("order_id", "customer_id", "refund", "reason")} == {
        "order_id": 1, "customer_id": 1, "refund": 600.0, "reason": "client",
    }


@pytest.mark.parametrize("status", ["processing", "ready"])
def test_failed_delivery_cancels_order_and_refunds(placed, storage, status):
    """Компенсация саги в unit-тестах не проверялась вовсе: выживало даже `not in` → `in`."""
    storage.orders[1].status = status

    order = placed.compensate_failed_delivery(1)

    assert order.status == "cancelled"
    assert storage.users[1].balance == 1000.0
    [event] = storage.outbox
    assert (event.payload["order_id"], event.payload["reason"]) == (1, "delivery_failed")


@pytest.mark.parametrize("status", ["cancelled", "delivered"])
def test_compensation_skips_finished_orders(placed, storage, status):
    storage.orders[1].status = status

    assert placed.compensate_failed_delivery(1) is None
    assert storage.users[1].balance == 400.0
    assert storage.outbox == []


def test_compensation_is_idempotent(placed, storage):
    """Повтор события: деньги возвращаются один раз."""
    placed.compensate_failed_delivery(1)
    storage.orders[1].status = "ready"  # будто статус вернули, а возврат уже был

    assert placed.compensate_failed_delivery(1) is None
    assert storage.users[1].balance == 1000.0
