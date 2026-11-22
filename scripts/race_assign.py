"""
20 одновременных назначений одного курьера на 20 разных заказов.

    python -m scripts.race_assign check      # как в лабе 5: SELECT, потом INSERT
    python -m scripts.race_assign service    # DeliveryCore микросервиса

Нужен PostgreSQL с заказами 1..20 и курьером 4 (см. README, «Гонка»).
Таблица deliveries после прогона не чистится.
"""
import argparse
import threading

from delivery_service.config import DeliverySettings
from delivery_service.core import Conflict, DeliveryCore
from delivery_service.storage import (
    IN_PROGRESS,
    ActiveDeliveryExists,
    DeliveryStore,
    make_session_factory,
)

COURIER_ID = 4
N = 20


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("check", "service"))
    args = parser.parse_args()

    store = DeliveryStore(make_session_factory(DeliverySettings().database_url))
    core = DeliveryCore(store)
    barrier = threading.Barrier(N)
    assigned = []

    def assign(order_id: int) -> None:
        barrier.wait()
        if args.mode == "check":
            if any(d.status == IN_PROGRESS for d in store.list_by_courier(COURIER_ID)):
                return
            try:
                store.create(order_id, COURIER_ID)
            except ActiveDeliveryExists:
                return  # проверку проскочили, остановил индекс
        else:
            try:
                core.assign(order_id, COURIER_ID)
            except Conflict:
                return
        assigned.append(order_id)

    threads = [threading.Thread(target=assign, args=(i + 1,)) for i in range(N)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    print(f"{args.mode}: назначено {len(assigned)} из {N}, активных доставок у курьера должно быть 1")


if __name__ == "__main__":
    main()
