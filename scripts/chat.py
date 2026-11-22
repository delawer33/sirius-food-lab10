"""
Консольный чат клиента и курьера (Bidirectional Streaming ChatWithCourier).

    python -m scripts.chat 1 --as client      # терминал 1
    python -m scripts.chat 1 --as courier     # терминал 2

Строка из stdin уходит собеседнику, его сообщения печатаются сразу.
--say "текст" отправляет одно сообщение, ждёт ответа и выходит.
"""
import argparse
import queue
import sys
import threading
from datetime import datetime

from app.core.config import settings
from app.domain.errors import DomainError
from app.infrastructure.delivery_grpc import GrpcDeliveryGateway, get_channel
from delivery_grpc import delivery_pb2 as pb


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("delivery_id", type=int)
    parser.add_argument("--as", dest="author", choices=("client", "courier"), default="client")
    parser.add_argument("--say", help="отправить одно сообщение, дождаться ответа и выйти")
    parser.add_argument("--target", default=settings.DELIVERY_GRPC_TARGET)
    args = parser.parse_args()

    outgoing: queue.Queue = queue.Queue()

    def send(text: str) -> None:
        outgoing.put(pb.ChatMessage(delivery_id=args.delivery_id, author=args.author, text=text))

    send(args.say or "")  # первое сообщение — вход в комнату доставки
    if not args.say:
        def read_stdin():
            for line in sys.stdin:
                if line.strip():
                    send(line.strip())
            outgoing.put(None)

        threading.Thread(target=read_stdin, daemon=True).start()
        print(f"Чат доставки {args.delivery_id}, вы — {args.author}. Ctrl+D — выход.")

    gateway = GrpcDeliveryGateway(get_channel(args.target))
    try:
        for message in gateway.chat(iter(outgoing.get, None)):
            sent = datetime.fromtimestamp(message.sent_at_ms / 1000)
            print(f"{sent:%H:%M:%S} [{message.author}] {message.text}", flush=True)
            if args.say and message.author != args.author:
                break
    except DomainError as error:
        sys.exit(f"Ошибка: {error.message}")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
