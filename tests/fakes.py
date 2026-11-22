"""Подставные реализации портов для тестов."""
from app.modules.orders.interfaces import OrderNotifier


class RecordingNotifier(OrderNotifier):
    """Запоминает вызовы вместо постановки задач в Celery."""

    def __init__(self):
        self.calls: list[tuple] = []

    def order_created(self, order_id: int, email: str, phone: str | None) -> None:
        self.calls.append((order_id, email, phone))
