"""
Микросервис доставки через сгенерированный Stub, как его вызвал бы любой
клиент: коды ошибок, Server Streaming и Bidirectional Streaming.
"""
import queue
import threading
import time

import grpc
import pytest

from delivery_grpc import delivery_pb2 as pb
from delivery_grpc import delivery_pb2_grpc as pb_grpc


@pytest.fixture
def stub(delivery_server):
    return pb_grpc.DeliveryServiceStub(delivery_server.channel)


@pytest.fixture
def delivery(stub):
    return stub.AssignCourier(pb.AssignCourierRequest(order_id=10, courier_id=2)).delivery_id


def code_of(call) -> grpc.StatusCode:
    with pytest.raises(grpc.RpcError) as error:
        call()
    return error.value.code()


# --- Unary -----------------------------------------------------------------------

def test_get_delivery_by_order_and_by_id(stub, delivery):
    by_order = stub.GetDelivery(pb.GetDeliveryRequest(order_id=10))
    by_id = stub.GetDelivery(pb.GetDeliveryRequest(delivery_id=delivery))

    assert by_order == by_id
    assert (by_id.id, by_id.order_id, by_id.courier_id, by_id.status) == (delivery, 10, 2, "in_progress")


def test_error_codes(stub, delivery):
    assert code_of(lambda: stub.GetDelivery(pb.GetDeliveryRequest(order_id=999))) == grpc.StatusCode.NOT_FOUND
    assert code_of(lambda: stub.GetDelivery(pb.GetDeliveryRequest())) == grpc.StatusCode.INVALID_ARGUMENT
    assert code_of(
        lambda: stub.AssignCourier(pb.AssignCourierRequest(order_id=0, courier_id=2))
    ) == grpc.StatusCode.INVALID_ARGUMENT
    assert code_of(
        lambda: stub.AssignCourier(pb.AssignCourierRequest(order_id=11, courier_id=2))
    ) == grpc.StatusCode.FAILED_PRECONDITION
    stub.CompleteDelivery(pb.CompleteDeliveryRequest(delivery_id=delivery))
    assert code_of(
        lambda: stub.CompleteDelivery(pb.CompleteDeliveryRequest(delivery_id=delivery))
    ) == grpc.StatusCode.FAILED_PRECONDITION


# --- Server Streaming ------------------------------------------------------------

def test_track_streams_statuses_in_order(stub, delivery):
    events = list(stub.TrackDelivery(pb.TrackDeliveryRequest(delivery_id=delivery)))

    assert [e.status for e in events] == ["in_progress", "on_the_way", "delivered"]
    assert all(e.delivery_id == delivery for e in events)
    assert events[0].at_ms <= events[1].at_ms <= events[2].at_ms


def test_track_jumps_to_delivered_when_completed(stub, delivery, delivery_server):
    stream = stub.TrackDelivery(pb.TrackDeliveryRequest(delivery_id=delivery))
    assert next(stream).status == "in_progress"

    stub.CompleteDelivery(pb.CompleteDeliveryRequest(delivery_id=delivery))

    assert [e.status for e in stream] == ["delivered"]


def test_track_unknown_delivery(stub):
    stream = stub.TrackDelivery(pb.TrackDeliveryRequest(delivery_id=999))
    assert code_of(lambda: list(stream)) == grpc.StatusCode.NOT_FOUND


# --- Bidirectional Streaming -----------------------------------------------------

class ChatClient:
    """Участник чата: свой поток отправки и свой поток приёма."""

    def __init__(self, stub, delivery_id: int, author: str):
        self.delivery_id, self.author = delivery_id, author
        self._outgoing: queue.Queue = queue.Queue()
        self.incoming: queue.Queue = queue.Queue()
        self.call = stub.ChatWithCourier(iter(self._outgoing.get, None))
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for message in self.call:
                self.incoming.put(message)
        except grpc.RpcError as error:
            self.incoming.put(error)

    def send(self, text: str = "") -> None:
        self._outgoing.put(pb.ChatMessage(delivery_id=self.delivery_id, author=self.author, text=text))

    def receive(self):
        return self.incoming.get(timeout=2)

    def close(self) -> None:
        self._outgoing.put(None)


@pytest.fixture
def chat(stub, delivery_server):
    clients = []

    def connect(delivery_id: int, author: str, join: bool = False) -> ChatClient:
        """join=True — войти пустым сообщением и дождаться, пока сервер это учтёт."""
        client = ChatClient(stub, delivery_id, author)
        clients.append(client)
        if join:
            client.send()
            deadline = time.monotonic() + 2
            while author not in delivery_server.hub.online(delivery_id):
                assert time.monotonic() < deadline, "участник не вошёл в чат"
                time.sleep(0.005)
        return client

    yield connect
    for client in clients:
        client.close()


def test_chat_relays_messages_both_ways(chat, delivery):
    courier = chat(delivery, "courier", join=True)
    client = chat(delivery, "client")
    client.send("Где вы?")

    received = courier.receive()
    assert (received.author, received.text) == ("client", "Где вы?")
    assert received.sent_at_ms > 0

    courier.send("Через 5 минут")
    assert client.receive().text == "Через 5 минут"


def test_chat_answers_when_courier_offline_and_replays_history(chat, delivery):
    client = chat(delivery, "client")
    client.send("Позвоните в домофон 12")

    answer = client.receive()
    assert answer.author == "system"
    assert "Курьер не в сети" in answer.text

    courier = chat(delivery, "courier", join=True)
    assert courier.receive().text == "Позвоните в домофон 12"


def test_chat_rooms_are_separate(chat, stub, delivery):
    other = stub.AssignCourier(pb.AssignCourierRequest(order_id=11, courier_id=3)).delivery_id
    courier = chat(delivery, "courier", join=True)
    stranger = chat(other, "client")
    stranger.send("Это не вам")

    assert stranger.receive().author == "system"
    assert courier.incoming.empty()


def test_chat_rejects_unknown_delivery_and_author(chat, delivery):
    unknown = chat(999, "client")
    unknown.send("Привет")
    assert unknown.receive().code() == grpc.StatusCode.NOT_FOUND

    intruder = chat(delivery, "hacker")
    intruder.send("Привет")
    assert intruder.receive().code() == grpc.StatusCode.INVALID_ARGUMENT
