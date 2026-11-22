"""
gRPC-сервер доставки: переводит вызовы в DeliveryCore, а его исключения —
в коды gRPC. Бизнес-правил здесь нет.
"""
import logging

import observability
from observability import tracing
import queue
import signal
import threading
import time
from concurrent import futures

import grpc

from delivery_grpc import delivery_pb2 as pb
from delivery_grpc import delivery_pb2_grpc as pb_grpc
from delivery_service.chat import ChatHub, Participant
from delivery_service.config import DeliverySettings
from delivery_service.core import Conflict, DeliveryCore, NotFound
from delivery_service.storage import CANCELLED, COMPLETED, DeliveryStore, make_session_factory

logger = logging.getLogger("delivery_service")

TRACK_STEPS = ("in_progress", "on_the_way", "delivered")
CHAT_AUTHORS = ("client", "courier")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_message(delivery) -> pb.GetDeliveryResponse:
    return pb.GetDeliveryResponse(
        id=delivery.id, status=delivery.status,
        courier_id=delivery.courier_id or 0, order_id=delivery.order_id,
    )


def _call(context, func, *args):
    """Вызов ядра с переводом его исключений в статусы gRPC."""
    try:
        return func(*args)
    except NotFound as error:
        context.abort(grpc.StatusCode.NOT_FOUND, str(error))
    except Conflict as error:
        context.abort(grpc.StatusCode.FAILED_PRECONDITION, str(error))


class DeliveryServicer(pb_grpc.DeliveryServiceServicer):
    def __init__(self, core: DeliveryCore, hub: ChatHub, track_interval: float = 2.0):
        self.core = core
        self.hub = hub
        self.track_interval = track_interval

    def AssignCourier(self, request, context):
        if request.order_id <= 0 or request.courier_id <= 0:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "order_id и courier_id обязательны")
        delivery = _call(context, self.core.assign, request.order_id, request.courier_id)
        logger.info("AssignCourier order=%s courier=%s -> delivery %s",
                    request.order_id, request.courier_id, delivery.id)
        return pb.AssignCourierResponse(delivery_id=delivery.id, status=delivery.status)

    def CompleteDelivery(self, request, context):
        delivery = _call(context, self.core.complete, request.delivery_id)
        logger.info("CompleteDelivery delivery=%s -> %s", delivery.id, delivery.status)
        return pb.CompleteDeliveryResponse(status=delivery.status)

    def GetDelivery(self, request, context):
        key = request.WhichOneof("key")
        if key == "delivery_id":
            delivery = _call(context, self.core.get, request.delivery_id)
        elif key == "order_id":
            delivery = _call(context, self.core.get_by_order, request.order_id)
        else:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Нужен delivery_id или order_id")
        logger.info("GetDelivery %s=%s -> delivery %s", key, getattr(request, key), delivery.id)
        return _to_message(delivery)

    def ListCourierDeliveries(self, request, context):
        deliveries = self.core.list_by_courier(request.courier_id)
        logger.info("ListCourierDeliveries courier=%s -> %s", request.courier_id, len(deliveries))
        return pb.ListCourierDeliveriesResponse(deliveries=[_to_message(d) for d in deliveries])

    def TrackDelivery(self, request, context):
        """
        Статусы in_progress → on_the_way → delivered с паузой track_interval.
        Движение курьера имитируется. Если доставку завершили по-настоящему
        (CompleteDelivery), поток сразу отдаёт delivered.
        """
        delivery_id = request.delivery_id
        delivery = _call(context, self.core.get, delivery_id)
        logger.info("TrackDelivery delivery=%s: подписка", delivery_id)
        if delivery.status == CANCELLED:
            yield pb.DeliveryStatus(delivery_id=delivery_id, status=CANCELLED, at_ms=_now_ms())
            return

        cancelled = threading.Event()
        context.add_callback(cancelled.set)
        for step, status in enumerate(TRACK_STEPS):
            if step and cancelled.wait(self.track_interval):
                logger.info("TrackDelivery delivery=%s: клиент отключился", delivery_id)
                return
            if self.core.get(delivery_id).status == COMPLETED:
                status = "delivered"
            yield pb.DeliveryStatus(delivery_id=delivery_id, status=status, at_ms=_now_ms())
            if status == "delivered":
                return

    def ChatWithCourier(self, request_iterator, context):
        """
        Первое сообщение определяет доставку и автора. Дальше входящие
        читает отдельный поток, а этот отдаёт клиенту сообщения собеседника.
        """
        first = next(request_iterator, None)
        if first is None:
            return
        if first.author not in CHAT_AUTHORS:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "author: client или courier")
        delivery_id = first.delivery_id
        _call(context, self.core.get, delivery_id)

        me, history = self.hub.join(delivery_id, first.author)
        logger.info("Chat delivery=%s: вошёл %s", delivery_id, first.author)

        def read_incoming():
            try:
                self._relay(delivery_id, me, first)
                for message in request_iterator:
                    self._relay(delivery_id, me, message)
            except grpc.RpcError:
                pass  # клиент оборвал соединение
            finally:
                me.inbox.put(None)

        threading.Thread(target=read_incoming, daemon=True).start()
        try:
            yield from history
            while context.is_active():
                try:
                    message = me.inbox.get(timeout=0.5)
                except queue.Empty:
                    continue
                if message is None:
                    return
                yield message
        finally:
            self.hub.leave(delivery_id, me)
            logger.info("Chat delivery=%s: вышел %s", delivery_id, me.author)

    def _relay(self, delivery_id: int, me: Participant, message) -> None:
        if not message.text:
            return
        stamped = pb.ChatMessage(delivery_id=delivery_id, author=me.author,
                                 text=message.text, sent_at_ms=_now_ms())
        if self.hub.publish(delivery_id, me, stamped) == 0:
            other = "Курьер" if me.author == "client" else "Клиент"
            me.inbox.put(pb.ChatMessage(
                delivery_id=delivery_id, author="system", sent_at_ms=_now_ms(),
                text=f"{other} не в сети, увидит сообщение, когда подключится",
            ))


def build_server(core: DeliveryCore, hub: ChatHub, address: str,
                 workers: int = 32, track_interval: float = 2.0) -> tuple[grpc.Server, int]:
    """
    Сервер и порт, на котором он слушает (address "...:0" — любой свободный).
    Каждый открытый поток (трекинг, чат) занимает поток пула, поэтому пул
    больше, чем 10 из методички.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=workers))
    pb_grpc.add_DeliveryServiceServicer_to_server(
        DeliveryServicer(core, hub, track_interval), server
    )
    port = server.add_insecure_port(address)
    return server, port


def serve() -> None:
    observability.setup("delivery-service")
    settings = DeliverySettings()
    session_factory = make_session_factory(settings.database_url)
    tracing.instrument_engine(session_factory.kw["bind"])
    store = DeliveryStore(session_factory)
    server, port = build_server(
        DeliveryCore(store), ChatHub(), f"[::]:{settings.DELIVERY_GRPC_PORT}",
        settings.DELIVERY_GRPC_WORKERS, settings.TRACK_INTERVAL,
    )
    server.start()
    logger.info("Delivery gRPC Server running on port %s", port)

    def shutdown(*_):
        # Новые вызовы не принимаются, текущим даётся 5 секунд.
        logger.info("Остановка")
        server.stop(grace=5)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    server.wait_for_termination()
