"""
Unit-тесты DeliveryService без СУБД.
"""
from dataclasses import replace

import pytest

from app.domain.entities import Delivery, Order, User
from app.domain.errors import AccessDeniedError, BusinessRuleError, NotFoundError
from app.modules.delivery.repository import InMemoryDeliveryGateway, InMemoryDeliveryRepository
from app.modules.delivery.service import DeliveryService

ANNA = User(1, "anna@sirius.ru", None, 0.0, False, "student")
BORIS = User(2, "boris@sirius.ru", None, 0.0, False, "student")
COURIER = User(3, "courier@sirius.ru", None, 0.0, False, "courier")
OTHER_COURIER = User(4, "courier2@sirius.ru", None, 0.0, False, "courier")
ADMIN = User(5, "admin@sirius.ru", None, 0.0, False, "admin")


@pytest.fixture
def service(storage):
    for user in (ANNA, BORIS, COURIER, OTHER_COURIER, ADMIN):
        storage.users[user.id] = replace(user)
    storage.orders[1] = Order(1, ANNA.id, 1, 1, "ready", 200.0)
    return DeliveryService(InMemoryDeliveryRepository(storage), InMemoryDeliveryGateway(storage))


@pytest.fixture
def assigned(service, storage):
    """Курьер 3 везёт заказ Анны."""
    service.assign_courier(1, COURIER.id)
    return service


def test_assign_creates_delivery_and_moves_order(service, storage):
    delivery = service.assign_courier(1, COURIER.id)

    assert storage.deliveries[delivery.id] == Delivery(1, 1, COURIER.id, "in_progress")
    assert storage.orders[1].status == "delivering"


def test_assign_requires_ready_order(service, storage):
    storage.orders[1].status = "processing"

    with pytest.raises(BusinessRuleError, match="готовый заказ"):
        service.assign_courier(1, COURIER.id)


def test_assign_unknown_order(service):
    with pytest.raises(NotFoundError, match="Заказ не найден"):
        service.assign_courier(999, COURIER.id)


def test_assign_requires_courier_role(service):
    with pytest.raises(BusinessRuleError, match="не является курьером"):
        service.assign_courier(1, BORIS.id)


def test_assign_blocked_courier(service, storage):
    storage.users[COURIER.id].is_blocked = True

    with pytest.raises(AccessDeniedError, match="заблокирован"):
        service.assign_courier(1, COURIER.id)


def test_one_active_delivery_per_courier(assigned, storage):
    storage.orders[2] = Order(2, BORIS.id, 1, 1, "ready", 200.0)

    with pytest.raises(BusinessRuleError, match="уже есть активная"):
        assigned.assign_courier(2, COURIER.id)


@pytest.mark.parametrize("actor", [COURIER, ANNA, ADMIN])
def test_delivery_visible_to_courier_owner_and_admin(assigned, actor):
    assert assigned.get_delivery(1, actor=actor).id == 1


@pytest.mark.parametrize("actor", [BORIS, OTHER_COURIER])
def test_delivery_hidden_from_others(assigned, actor):
    """Студент не видит доставку чужого заказа, курьер — чужую доставку."""
    with pytest.raises(AccessDeniedError):
        assigned.get_delivery(1, actor=actor)


def test_courier_lists_only_own_deliveries(assigned):
    assert [d.id for d in assigned.list_my_deliveries(COURIER)] == [1]
    assert assigned.list_my_deliveries(OTHER_COURIER) == []


def test_other_courier_cannot_complete(assigned, storage):
    with pytest.raises(AccessDeniedError, match="свою доставку"):
        assigned.complete_delivery(1, actor=OTHER_COURIER)
    assert storage.deliveries[1].status == "in_progress"


def test_complete_delivers_order(assigned, storage):
    assigned.complete_delivery(1, actor=COURIER)

    assert storage.deliveries[1].status == "completed"
    assert storage.orders[1].status == "delivered"
    with pytest.raises(BusinessRuleError, match="уже завершена"):
        assigned.complete_delivery(1, actor=COURIER)


def test_cancelled_delivery_cannot_be_completed(assigned, storage):
    storage.deliveries[1].status = "cancelled"

    with pytest.raises(BusinessRuleError, match="Отменённую"):
        assigned.complete_delivery(1, actor=ADMIN)


def test_complete_unknown_delivery(service):
    with pytest.raises(NotFoundError, match="Доставка не найдена"):
        service.complete_delivery(999, actor=ADMIN)
