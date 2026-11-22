"""
Контрактные тесты шлюзов доставки: gRPC-микросервис, старый путь в БД и
память ведут себя одинаково. Поэтому DELIVERY_BACKEND можно переключить
без правок сервиса.
"""
import pytest

from app.domain.entities import Delivery
from app.domain.errors import BusinessRuleError, NotFoundError
from app.modules.delivery.repository import InMemoryDeliveryGateway, SqlAlchemyDeliveryGateway


@pytest.fixture(params=["grpc", "local", "memory"])
def gateway(request, db_session, storage):
    if request.param == "grpc":
        return request.getfixturevalue("grpc_gateway")
    if request.param == "local":
        return SqlAlchemyDeliveryGateway(db_session)
    return InMemoryDeliveryGateway(storage)


def test_assign_get_list(gateway):
    first = gateway.assign(order_id=10, courier_id=2)
    second = gateway.assign(order_id=11, courier_id=3)

    assert first == Delivery(1, 10, 2, "in_progress")
    assert gateway.get(1) == first
    assert gateway.get(999) is None
    assert gateway.list_by_courier(2) == [first]
    assert gateway.list_by_courier(3) == [second]
    assert gateway.list_by_courier(4) == []


def test_courier_has_one_active_delivery(gateway):
    gateway.assign(order_id=10, courier_id=2)

    with pytest.raises(BusinessRuleError, match="активная доставка"):
        gateway.assign(order_id=11, courier_id=2)


def test_order_is_delivered_by_one_courier(gateway):
    gateway.assign(order_id=10, courier_id=2)

    with pytest.raises(BusinessRuleError, match="заказ уже везут"):
        gateway.assign(order_id=10, courier_id=3)


def test_complete_frees_courier(gateway):
    gateway.assign(order_id=10, courier_id=2)

    assert gateway.complete(1) == "completed"
    assert gateway.get(1).status == "completed"
    assert gateway.assign(order_id=11, courier_id=2).id == 2


def test_complete_twice(gateway):
    gateway.assign(order_id=10, courier_id=2)
    gateway.complete(1)

    with pytest.raises(BusinessRuleError, match="уже завершена"):
        gateway.complete(1)


def test_complete_unknown(gateway):
    with pytest.raises(NotFoundError):
        gateway.complete(999)


def test_track(gateway):
    if isinstance(gateway, SqlAlchemyDeliveryGateway):
        pytest.skip("Без микросервиса трекинга нет, отдаётся только текущий статус")
    gateway.assign(order_id=10, courier_id=2)

    assert list(gateway.track(1)) == ["in_progress", "on_the_way", "delivered"]

    gateway.complete(1)
    assert list(gateway.track(1)) == ["delivered"]
