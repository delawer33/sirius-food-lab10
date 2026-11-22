"""
Комнаты чата: одна на доставку. Сообщение участника уходит всем остальным
участникам комнаты. Последние сообщения хранятся, и подключившийся позже
курьер их получит.

История в памяти процесса: после перезапуска сервиса она пропадёт. Для
учебного чата достаточно; в продакшене — Redis Streams или таблица.
"""
import queue
import threading
from collections import defaultdict, deque

HISTORY_SIZE = 50


class Participant:
    def __init__(self, author: str):
        self.author = author
        self.inbox: queue.Queue = queue.Queue()


class ChatHub:
    def __init__(self):
        self._lock = threading.Lock()
        self._rooms: dict[int, list[Participant]] = defaultdict(list)
        self._history: dict[int, deque] = defaultdict(lambda: deque(maxlen=HISTORY_SIZE))

    def join(self, delivery_id: int, author: str) -> tuple[Participant, list]:
        """Вход в комнату. Возвращает участника и историю до его входа."""
        participant = Participant(author)
        with self._lock:
            self._rooms[delivery_id].append(participant)
            return participant, list(self._history[delivery_id])

    def leave(self, delivery_id: int, participant: Participant) -> None:
        with self._lock:
            room = self._rooms[delivery_id]
            if participant in room:
                room.remove(participant)

    def online(self, delivery_id: int) -> list[str]:
        """Кто сейчас в комнате."""
        with self._lock:
            return [p.author for p in self._rooms[delivery_id]]

    def publish(self, delivery_id: int, sender: Participant, message) -> int:
        """
        Разослать сообщение остальным. Возвращает, сколько собеседников
        с другой стороны (не того же автора) его получили.
        """
        with self._lock:
            self._history[delivery_id].append(message)
            others = [p for p in self._rooms[delivery_id] if p is not sender]
        for participant in others:
            participant.inbox.put(message)
        return sum(1 for p in others if p.author != sender.author)
