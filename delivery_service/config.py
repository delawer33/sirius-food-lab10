"""
Настройки микросервиса. Свои, не из app.core.config: у сервиса своя жизнь,
ему не нужны ни SECRET_KEY, ни Redis монолита.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class DeliverySettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Своя БД сервиса. Пока таблица deliveries физически лежит в базе
    # монолита, поэтому по умолчанию берётся DATABASE_URL.
    DELIVERY_DATABASE_URL: str = ""
    DATABASE_URL: str = ""

    DELIVERY_GRPC_PORT: int = 50051
    DELIVERY_GRPC_WORKERS: int = 32
    # Пауза между статусами в TrackDelivery, секунды.
    TRACK_INTERVAL: float = 2.0
    # Consumer события order.paid (delivery_worker.py).
    RABBITMQ_URL: str = "amqp://sirius:sirius@localhost:5672/"

    @property
    def database_url(self) -> str:
        url = self.DELIVERY_DATABASE_URL or self.DATABASE_URL
        if not url:
            raise RuntimeError("Задайте DELIVERY_DATABASE_URL или DATABASE_URL")
        return url
