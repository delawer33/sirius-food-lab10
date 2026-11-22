"""
Основные флоу доставки по шагам, для показа на защите.

    python -m scripts.demo_delivery              # список флоу
    python -m scripts.demo_delivery happy        # один флоу
    python -m scripts.demo_delivery all          # все подряд, Enter между ними

Каждый шаг — HTTP-запрос к монолиту. Запросы к доставкам монолит переводит
в вызовы gRPC: их видно в терминале delivery_server.py.
"""
import os
import queue
import signal
import subprocess
import sys
import threading
import time

import httpx

from app.core.config import settings
from app.infrastructure.delivery_grpc import GrpcDeliveryGateway, get_channel
from delivery_grpc import delivery_pb2 as pb

HOST = "http://127.0.0.1:8010"
PASSWORD = "sirius-demo"


class Demo:
    def __init__(self, client: httpx.Client):
        self.client = client
        self.student = self.login("student@sirius.ru")
        self.student2 = self.login("student2@sirius.ru")
        self.cook = self.login("cook@sirius.ru")
        self.admin = self.login("admin@sirius.ru")
        self.courier = self.login("courier@sirius.ru")
        self.courier_id = client.get("/users/me", headers=self.courier).json()["id"]
        self.student2_id = client.get("/users/me", headers=self.student2).json()["id"]
        student_id = client.get("/users/me", headers=self.student).json()["id"]
        client.post(f"/users/{student_id}/topup", params={"amount": 1000}, headers=self.admin)

    def login(self, email: str) -> dict:
        response = self.client.post("/auth/login", json={"email": email, "password": PASSWORD})
        response.raise_for_status()
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def call(self, who: str, method: str, url: str, headers: dict,
             json: dict | None = None, grpc: str = "", note: str = "") -> httpx.Response:
        body = f" {json}" if json else ""
        print(f"[{who}] {method} {url}{body}")
        started = time.perf_counter()
        response = self.client.request(method, url, json=json, headers=headers)
        ms = (time.perf_counter() - started) * 1000
        print(f"  ← {response.status_code} за {ms:.0f} мс: {response.text}")
        if grpc:
            print(f"  gRPC: {grpc}")
        if note:
            print(f"  {note}")
        return response

    def ready_order(self) -> int:
        """Заказ, который кухня приготовила. Это монолит, gRPC не участвует."""
        order_id = self.client.post("/orders/create", json={"item_id": 1, "quantity": 1},
                                    headers=self.student).json()["order_id"]
        self.client.post(f"/kitchen/orders/{order_id}/ready", headers=self.cook)
        print(f"(подготовка: студент заказал, повар приготовил — заказ {order_id} в статусе ready)")
        return order_id

    def assign(self, order_id: int, courier_id: int | None = None, **kw) -> httpx.Response:
        return self.call("админ", "POST", "/delivery/assign", self.admin,
                         {"order_id": order_id, "courier_id": courier_id or self.courier_id}, **kw)

    def complete(self, delivery_id: int, **kw) -> httpx.Response:
        return self.call("курьер", "PATCH", f"/delivery/{delivery_id}/complete", self.courier, **kw)

    def free_courier(self) -> None:
        """Завершить активные доставки курьера, оставшиеся от прошлых показов."""
        response = self.client.get("/delivery/my", headers=self.courier)
        if response.status_code != 200:
            sys.exit(f"Сервис доставки не отвечает ({response.status_code}). Запустите delivery_server.py.")
        for delivery in response.json():
            if delivery["status"] == "in_progress":
                self.client.patch(f"/delivery/{delivery['id']}/complete", headers=self.courier)
                print(f"(подготовка: завершена старая доставка {delivery['id']}, курьер свободен)")


def title(text: str) -> None:
    print(f"\n{'=' * 70}\n{text}\n{'=' * 70}\n")


# --- Флоу ------------------------------------------------------------------------

def happy(d: Demo) -> None:
    """Весь путь: назначение, чтение, трекинг, завершение."""
    title("Путь доставки: назначение → трекинг → завершение")
    d.free_courier()
    order_id = d.ready_order()

    print("\n--- 1. Назначение курьера\n")
    delivery_id = d.assign(order_id, grpc="AssignCourier — сервис создал доставку in_progress").json()["delivery_id"]
    d.call("студент", "GET", f"/orders/{order_id}", d.student,
           note="заказ стал delivering: доставка создана в сервисе, статус заказа сменил монолит")

    print("\n--- 2. Чтение\n")
    d.call("курьер", "GET", "/delivery/my", d.courier, grpc="ListCourierDeliveries")
    d.call("студент", "GET", f"/delivery/{delivery_id}", d.student, grpc="GetDelivery",
           note="кто имеет право смотреть, проверил монолит: это заказ студента")

    print("\n--- 3. Трекинг: Server Streaming, монолит отдаёт его как SSE\n")
    print(f"[студент] GET /delivery/{delivery_id}/track")
    started = time.perf_counter()
    with d.client.stream("GET", f"/delivery/{delivery_id}/track", headers=d.student) as stream:
        print(f"  ← {stream.status_code}, {stream.headers['content-type']}")
        for line in stream.iter_lines():
            if line:
                print(f"  +{time.perf_counter() - started:3.1f} с  {line}")
    print("  gRPC: TrackDelivery — один запрос, три ответа по мере смены статуса")

    print("\n--- 4. Завершение\n")
    d.complete(delivery_id, grpc="CompleteDelivery")
    d.call("студент", "GET", f"/orders/{order_id}", d.student, note="заказ delivered")


def rules(d: Demo) -> None:
    """Бизнес-правила: какие проверяет монолит, какие сервис."""
    title("Правила: монолит проверяет заказы и людей, сервис — доставки")
    d.free_courier()

    print("--- Монолит: заказ ещё не готов\n")
    order_id = d.client.post("/orders/create", json={"item_id": 1, "quantity": 1},
                             headers=d.student).json()["order_id"]
    print(f"(подготовка: заказ {order_id} в статусе processing, повар его не приготовил)")
    d.assign(order_id, note="отказал монолит, до gRPC дело не дошло")

    print("\n--- Монолит: назначают не курьера\n")
    order_id = d.ready_order()
    d.assign(order_id, courier_id=d.student2_id, note="student2 — не курьер, отказал монолит")

    print("\n--- Сервис: у курьера уже есть активная доставка\n")
    delivery_id = d.assign(order_id, grpc="AssignCourier — создана").json()["delivery_id"]
    second = d.ready_order()
    d.assign(second, grpc="AssignCourier → FAILED_PRECONDITION",
             note="отказал сервис, монолит перевёл в 400. Правило держит уникальный индекс в БД")

    print("\n--- Монолит: чужой студент смотрит доставку\n")
    d.call("student2", "GET", f"/delivery/{delivery_id}", d.student2, grpc="GetDelivery",
           note="доставка получена из сервиса, но монолит не дал её чужому: 403 (IDOR)")

    print("\n--- Сервис: завершить дважды\n")
    d.complete(delivery_id, grpc="CompleteDelivery")
    d.complete(delivery_id, grpc="CompleteDelivery → FAILED_PRECONDITION", note="отказал сервис")


def chat(d: Demo) -> None:
    """Bidirectional Streaming: клиент и курьер в одном скрипте, двумя потоками."""
    title("Чат клиента и курьера: Bidirectional Streaming")
    d.free_courier()
    order_id = d.ready_order()
    delivery_id = d.assign(order_id, grpc="AssignCourier").json()["delivery_id"]
    gateway = GrpcDeliveryGateway(get_channel(settings.DELIVERY_GRPC_TARGET))

    class Side:
        """Участник: свой поток исходящих, свой поток входящих."""

        def __init__(self, author: str, label: str):
            self.author, self.label = author, label
            self.outgoing: queue.Queue = queue.Queue()
            self.received = threading.Event()
            self.say("")  # пустое сообщение — вход в комнату доставки
            threading.Thread(target=self.read, daemon=True).start()

        def say(self, text: str) -> None:
            if text:
                print(f"  {self.label} пишет:  {text}")
            self.outgoing.put(pb.ChatMessage(delivery_id=delivery_id, author=self.author, text=text))

        def read(self) -> None:
            for message in gateway.chat(iter(self.outgoing.get, None)):
                print(f"  {self.label} видит:  [{message.author}] {message.text}")
                self.received.set()

        def wait(self) -> None:
            self.received.wait(3)
            self.received.clear()
            time.sleep(0.2)

        def close(self) -> None:
            self.outgoing.put(None)

    print("\n--- Курьер ещё не в сети\n")
    client = Side("client", "клиент")
    time.sleep(0.3)
    client.say("Позвоните в домофон 12")
    client.wait()

    print("\n--- Курьер подключился: получает то, что пропустил\n")
    courier = Side("courier", "курьер ")
    courier.wait()

    print("\n--- Переписка в обе стороны\n")
    client.say("Где вы?")
    courier.wait()
    courier.say("Уже подъезжаю, буду через 5 минут")
    client.wait()

    client.close()
    courier.close()
    print("\n  один открытый поток на участника, сообщения идут в обе стороны независимо")
    d.complete(delivery_id)


def down(d: Demo) -> None:
    """UNAVAILABLE: сервис остановлен."""
    title("Сервис доставки упал: UNAVAILABLE → 503")
    d.free_courier()
    order_id = d.ready_order()
    input("\nОстановите delivery_server.py (Ctrl+C в его вкладке), затем Enter ")

    print()
    d.assign(order_id, grpc="AssignCourier → UNAVAILABLE",
             note="ответ сразу: порт закрыт, ждать таймаута незачем")
    d.call("курьер", "GET", "/delivery/my", d.courier, grpc="ListCourierDeliveries → UNAVAILABLE (3 попытки)")
    d.call("студент", "GET", f"/orders/{order_id}", d.student, note="заказ остался ready")
    d.call("студент", "GET", "/menu/items", d.student, note="остальной монолит работает")

    input("\nЗапустите delivery_server.py снова, затем Enter ")
    print()
    for _ in range(10):
        response = d.assign(order_id, grpc="AssignCourier")
        if response.status_code != 503:
            break
        print("  сервис ещё поднимается, повтор через секунду\n")
        time.sleep(1)
    if response.status_code == 200:
        d.complete(response.json()["delivery_id"])


def timeout(d: Demo) -> None:
    """DEADLINE_EXCEEDED: сервис завис (процесс приостановлен)."""
    title("Сервис доставки завис: DEADLINE_EXCEEDED → 504")
    pids = subprocess.run(["pgrep", "-f", "^[^ ]*python[0-9.]* delivery_server.py"],
                          capture_output=True, text=True).stdout.split()
    if not pids:
        sys.exit("delivery_server.py не запущен")
    pid = int(pids[0])

    print(f"kill -STOP {pid}   # процесс сервиса заморожен: порт открыт, но никто не отвечает\n")
    os.kill(pid, signal.SIGSTOP)
    try:
        d.call("курьер", "GET", "/delivery/my", d.courier, grpc="ListCourierDeliveries → DEADLINE_EXCEEDED",
               note=f"монолит ждал DELIVERY_GRPC_TIMEOUT={settings.DELIVERY_GRPC_TIMEOUT} с и отдал 504, "
                    "а не висел вечно")
    finally:
        os.kill(pid, signal.SIGCONT)
    print(f"\nkill -CONT {pid}   # сервис снова работает")
    print("(во вкладке сервиса zsh напишет «suspended»: процесс продолжил работу в фоне,")
    print(" чтобы Ctrl+C снова до него доходил, введите там fg)\n")
    d.call("курьер", "GET", "/delivery/my", d.courier, grpc="ListCourierDeliveries")


FLOWS = {"happy": happy, "rules": rules, "chat": chat, "down": down, "timeout": timeout}


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else ""
    if name not in (*FLOWS, "all"):
        print(__doc__)
        for key, flow in FLOWS.items():
            print(f"  {key:8} {flow.__doc__.strip()}")
        return

    with httpx.Client(base_url=HOST, timeout=30) as client:
        demo = Demo(client)
        flows = FLOWS if name == "all" else {name: FLOWS[name]}
        for n, flow in enumerate(flows.values()):
            if n:
                input("\nEnter — следующий флоу ")
            flow(demo)


if __name__ == "__main__":
    main()
