"""
Микросервис доставки, отдельный процесс. Слушает порт 50051.

    python delivery_server.py
"""
from delivery_service.server import serve

if __name__ == "__main__":
    serve()
