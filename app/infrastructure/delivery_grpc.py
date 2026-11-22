"""
gRPC-клиент сервиса доставки: адаптер порта DeliveryGateway.

Сервис монолита вызывает методы порта и получает доменные сущности и
доменные исключения. Про grpc, каналы и коды статусов знает только этот файл.
"""
import json
import logging
from collections.abc import Iterator
from functools import lru_cache

import grpc

from app.domain.entities import Delivery
from app.domain.errors import (
    BusinessRuleError,
    NotFoundError,
    ServiceTimeoutError,
    ServiceUnavailableError,
)
from app.modules.delivery.interfaces import DeliveryGateway
from delivery_grpc import delivery_pb2 as pb
from delivery_grpc import delivery_pb2_grpc as pb_grpc

logger = logging.getLogger(__name__)

# Чтение можно безопасно повторить: если сервис на миг недоступен
# (перезапуск), канал сам повторит вызов. AssignCourier и CompleteDelivery
# не повторяются: если первый вызов дошёл, а ответ потерялся, повтор
# вернёт «курьер занят» или «уже завершена», хотя всё получилось.
_RETRY_READS = {
    "methodConfig": [{
        "name": [
            {"service": "delivery.DeliveryService", "method": "GetDelivery"},
            {"service": "delivery.DeliveryService", "method": "ListCourierDeliveries"},
        ],
        "retryPolicy": {
            "maxAttempts": 3,
            "initialBackoff": "0.1s",
            "maxBackoff": "0.5s",
            "backoffMultiplier": 2,
            "retryableStatusCodes": ["UNAVAILABLE"],
        },
    }]
}

CHANNEL_OPTIONS = [
    ("grpc.enable_retries", 1),
    ("grpc.service_config", json.dumps(_RETRY_READS)),
    # По умолчанию после обрыва канал ждёт переподключения до 2 минут:
    # сервис уже поднялся, а монолит всё ещё отвечает 503.
    ("grpc.initial_reconnect_backoff_ms", 200),
    ("grpc.min_reconnect_backoff_ms", 200),
    ("grpc.max_reconnect_backoff_ms", 2000),
]

# Поток трекинга живёт дольше обычного вызова.
TRACK_TIMEOUT = 60.0


@lru_cache
def get_channel(target: str) -> grpc.Channel:
    """
    Один канал на процесс. Канал — это HTTP/2-соединение с пулом потоков
    внутри; создавать его на каждый запрос, как в методичке, дорого.
    """
    return grpc.insecure_channel(target, options=CHANNEL_OPTIONS)


def translate(error: grpc.RpcError) -> Exception:
    """Код gRPC → доменное исключение."""
    code, details = error.code(), error.details()
    if code == grpc.StatusCode.NOT_FOUND:
        return NotFoundError(details)
    if code in (grpc.StatusCode.FAILED_PRECONDITION, grpc.StatusCode.INVALID_ARGUMENT):
        return BusinessRuleError(details)
    if code == grpc.StatusCode.DEADLINE_EXCEEDED:
        return ServiceTimeoutError("Сервис доставки не ответил вовремя")
    if code == grpc.StatusCode.UNAVAILABLE:
        return ServiceUnavailableError("Сервис доставки недоступен")
    logger.error("Сервис доставки вернул %s: %s", code.name, details)
    return ServiceUnavailableError(f"Ошибка сервиса доставки: {code.name}")


def _to_entity(message: pb.GetDeliveryResponse) -> Delivery:
    return Delivery(message.id, message.order_id, message.courier_id, message.status)


class GrpcDeliveryGateway(DeliveryGateway):
    def __init__(self, channel: grpc.Channel, timeout: float = 2.0):
        self.stub = pb_grpc.DeliveryServiceStub(channel)
        self.timeout = timeout

    def _call(self, method, request):
        try:
            return method(request, timeout=self.timeout)
        except grpc.RpcError as error:
            raise translate(error) from None

    def assign(self, order_id: int, courier_id: int) -> Delivery:
        response = self._call(
            self.stub.AssignCourier,
            pb.AssignCourierRequest(order_id=order_id, courier_id=courier_id),
        )
        return Delivery(response.delivery_id, order_id, courier_id, response.status)

    def get(self, delivery_id: int) -> Delivery | None:
        try:
            response = self._call(self.stub.GetDelivery, pb.GetDeliveryRequest(delivery_id=delivery_id))
        except NotFoundError:
            return None
        return _to_entity(response)

    def list_by_courier(self, courier_id: int) -> list[Delivery]:
        response = self._call(
            self.stub.ListCourierDeliveries, pb.ListCourierDeliveriesRequest(courier_id=courier_id)
        )
        return [_to_entity(d) for d in response.deliveries]

    def complete(self, delivery_id: int) -> str:
        response = self._call(
            self.stub.CompleteDelivery, pb.CompleteDeliveryRequest(delivery_id=delivery_id)
        )
        return response.status

    def track(self, delivery_id: int) -> Iterator[str]:
        stream = self.stub.TrackDelivery(
            pb.TrackDeliveryRequest(delivery_id=delivery_id), timeout=TRACK_TIMEOUT
        )
        try:
            for event in stream:
                yield event.status
        except grpc.RpcError as error:
            raise translate(error) from None
        finally:
            # Клиент ушёл раньше конца потока — сервер перестанет слать статусы.
            stream.cancel()

    def chat(self, outgoing: Iterator[pb.ChatMessage]) -> Iterator[pb.ChatMessage]:
        """
        Чат с курьером для scripts/chat.py. Не входит в порт: веб-клиента
        для чата в монолите нет, только консольный.
        """
        try:
            yield from self.stub.ChatWithCourier(outgoing)
        except grpc.RpcError as error:
            if error.code() != grpc.StatusCode.CANCELLED:
                raise translate(error) from None
