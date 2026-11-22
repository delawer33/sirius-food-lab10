"""
Подписка на статусы доставки (Server Streaming TrackDelivery).

    python -m scripts.track_delivery 1

Ходит в микросервис через тот же клиент, что и монолит.
"""
import argparse
import sys
from datetime import datetime

from app.core.config import settings
from app.domain.errors import DomainError
from app.infrastructure.delivery_grpc import GrpcDeliveryGateway, get_channel


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("delivery_id", type=int)
    parser.add_argument("--target", default=settings.DELIVERY_GRPC_TARGET)
    args = parser.parse_args()

    gateway = GrpcDeliveryGateway(get_channel(args.target))
    try:
        for status in gateway.track(args.delivery_id):
            print(f"{datetime.now():%H:%M:%S}  {status}", flush=True)
    except DomainError as error:
        sys.exit(f"Ошибка: {error.message}")


if __name__ == "__main__":
    main()
