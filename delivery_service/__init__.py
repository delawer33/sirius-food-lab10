"""
Микросервис доставки. Отдельный процесс: python delivery_server.py

Не импортирует ничего из app/: монолит и сервис общаются только по gRPC
через контракт proto/delivery.proto. Это проверяет tests/test_architecture.py.
"""
