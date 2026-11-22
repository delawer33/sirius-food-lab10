"""
Доставка через HTTP монолита. На бэкенде sql запросы идут в настоящий
gRPC-сервер (фикстура api), на memory — в шлюз в памяти.
"""
import socket
import time
from concurrent import futures

import grpc
import pytest

from app import container
from app.infrastructure.delivery_grpc import CHANNEL_OPTIONS, GrpcDeliveryGateway
from app.main import app
from delivery_grpc import delivery_pb2_grpc as pb_grpc


@pytest.fixture
def ready_order(api):
    """Студент заказал, кухня приготовила. Есть администратор и курьер."""
    cook = api.create_user("cook@sirius.ru", "cook")
    api.client.post("/menu/items", json={"name": "Борщ", "price": 200}, headers=api.headers(cook))
    student = api.create_user("anna@sirius.ru", balance=1000)
    order_id = api.client.post(
        "/orders/create", json={"item_id": 1, "quantity": 1}, headers=api.headers(student)
    ).json()["order_id"]
    api.client.post(f"/kitchen/orders/{order_id}/ready", headers=api.headers(cook))
    admin = api.create_user("admin@sirius.ru", "admin")
    courier = api.create_user("courier@sirius.ru", "courier")
    return student, admin, courier, order_id


def assign(api, admin, order_id, courier_id):
    return api.client.post(
        "/delivery/assign", json={"order_id": order_id, "courier_id": courier_id},
        headers=api.headers(admin),
    )


def order_status(api, student, order_id) -> str:
    return api.client.get(f"/orders/{order_id}", headers=api.headers(student)).json()["status"]


def test_full_delivery_flow(api, ready_order):
    student, admin, courier, order_id = ready_order

    response = assign(api, admin, order_id, courier.id)
    assert response.status_code == 200
    delivery_id = response.json()["delivery_id"]
    assert order_status(api, student, order_id) == "delivering"

    mine = api.client.get("/delivery/my", headers=api.headers(courier)).json()
    assert mine == [{"id": delivery_id, "order_id": order_id, "courier_id": courier.id, "status": "in_progress"}]

    done = api.client.patch(f"/delivery/{delivery_id}/complete", headers=api.headers(courier))
    assert done.status_code == 200
    assert order_status(api, student, order_id) == "delivered"
    assert api.client.get(f"/delivery/{delivery_id}", headers=api.headers(student)).json()["status"] == "completed"

    again = api.client.patch(f"/delivery/{delivery_id}/complete", headers=api.headers(courier))
    assert (again.status_code, again.json()["detail"]) == (400, "Доставка уже завершена")


def test_busy_courier_400(api, ready_order):
    student, admin, courier, order_id = ready_order
    assign(api, admin, order_id, courier.id)
    cook = api.create_user("cook2@sirius.ru", "cook")
    second = api.client.post(
        "/orders/create", json={"item_id": 1, "quantity": 1}, headers=api.headers(student)
    ).json()["order_id"]
    api.client.post(f"/kitchen/orders/{second}/ready", headers=api.headers(cook))

    response = assign(api, admin, second, courier.id)

    assert response.status_code == 400
    assert "активная доставка" in response.json()["detail"]
    # Заказ не сдвинулся: доставка не создана.
    assert order_status(api, student, second) == "ready"


def test_track_server_sent_events(api, ready_order):
    student, admin, courier, order_id = ready_order
    delivery_id = assign(api, admin, order_id, courier.id).json()["delivery_id"]

    response = api.client.get(f"/delivery/{delivery_id}/track", headers=api.headers(student))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text == "data: in_progress\n\ndata: on_the_way\n\ndata: delivered\n\n"


def test_track_foreign_delivery_403(api, ready_order):
    _, admin, courier, order_id = ready_order
    delivery_id = assign(api, admin, order_id, courier.id).json()["delivery_id"]
    outsider = api.create_user("boris@sirius.ru")

    response = api.client.get(f"/delivery/{delivery_id}/track", headers=api.headers(outsider))

    assert response.status_code == 403


# --- Сеть: сервис доставки недоступен или не отвечает ----------------------------

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def use_gateway(gateway: GrpcDeliveryGateway) -> None:
    app.dependency_overrides[container.get_delivery_gateway] = lambda: gateway


@pytest.fixture
def sql_api(api):
    if api.backend != "sql":
        pytest.skip("Сетевые ошибки бывают только у gRPC-шлюза")
    return api


def test_service_down_503(sql_api, ready_order):
    student, admin, courier, order_id = ready_order
    channel = grpc.insecure_channel(f"127.0.0.1:{free_port()}", options=CHANNEL_OPTIONS)
    use_gateway(GrpcDeliveryGateway(channel, timeout=1.0))

    started = time.monotonic()
    response = assign(sql_api, admin, order_id, courier.id)

    assert response.status_code == 503
    assert response.json()["detail"] == "Сервис доставки недоступен"
    # Отказ быстрый: монолит не ждёт таймаута, когда порт закрыт.
    assert time.monotonic() - started < 1.0
    # Заказ не сдвинулся.
    assert order_status(sql_api, student, order_id) == "ready"
    # Все эндпоинты доставки отвечают 503, а не 500.
    for url, user in (("/delivery/my", courier), ("/delivery/1", student), ("/delivery/1/track", student)):
        assert sql_api.client.get(url, headers=sql_api.headers(user)).status_code == 503, url
    assert sql_api.client.patch("/delivery/1/complete", headers=sql_api.headers(courier)).status_code == 503
    channel.close()


class SlowServicer(pb_grpc.DeliveryServiceServicer):
    def AssignCourier(self, request, context):
        time.sleep(1)


def test_service_timeout_504(sql_api, ready_order):
    _, admin, courier, order_id = ready_order
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    pb_grpc.add_DeliveryServiceServicer_to_server(SlowServicer(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    channel = grpc.insecure_channel(f"127.0.0.1:{port}", options=CHANNEL_OPTIONS)
    use_gateway(GrpcDeliveryGateway(channel, timeout=0.2))

    started = time.monotonic()
    response = assign(sql_api, admin, order_id, courier.id)

    assert response.status_code == 504
    assert response.json()["detail"] == "Сервис доставки не ответил вовремя"
    assert time.monotonic() - started < 0.9
    channel.close()
    server.stop(0)


def test_local_backend_without_microservice(sql_api, ready_order, monkeypatch):
    """Strangler Fig: DELIVERY_BACKEND=local возвращает старый путь в БД."""
    student, admin, courier, order_id = ready_order
    app.dependency_overrides.pop(container.get_delivery_gateway)
    monkeypatch.setattr(container.settings, "DELIVERY_BACKEND", "local")

    response = assign(sql_api, admin, order_id, courier.id)

    assert response.status_code == 200
    assert order_status(sql_api, student, order_id) == "delivering"
