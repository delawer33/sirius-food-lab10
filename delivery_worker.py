"""
Consumer микросервиса доставки, отдельный процесс рядом с delivery_server.py.

    python delivery_worker.py
"""
from delivery_service.worker import run

if __name__ == "__main__":
    run()
