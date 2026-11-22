"""
Настройки приложения. Читаются из переменных окружения и файла .env.

Secure by Default: у SECRET_KEY и DATABASE_URL нет значений по умолчанию,
без них приложение не запустится. Swagger выключен, пока явно не включён
DEBUG, а CORS по умолчанию не пускает ни один чужой домен.
"""
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения, загружаемые из .env."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    SECRET_KEY: str
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379"
    DEBUG: bool = False
    ALLOWED_ORIGINS: list[str] = []

    # sql — SQLAlchemy по DATABASE_URL, memory — хранилище в памяти процесса.
    REPO_BACKEND: str = "sql"
    # 1 — печатать выполняемые SQL-запросы в терминал.
    SQL_ECHO: bool = False
    # Пул соединений SQLAlchemy на процесс. По умолчанию — значения SQLAlchemy
    # (5 + 10, ожидание 30 с). Под нагрузкой пул меньше пула потоков FastAPI
    # (40) — узкое место, см. README ЛР № 10, раздел «Нагрузка».
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: float = 30.0

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    RATE_LIMIT_ENABLED: bool = True

    # Кеш меню в Redis (Cache-Aside). False — все чтения идут в БД.
    CACHE_ENABLED: bool = True
    # Меню меняется раз в день, но изменения должны быть видны быстро.
    # Событийная инвалидация сбрасывает кеш сразу, TTL — страховка.
    MENU_CACHE_TTL: int = 300
    # Категории меняются реже блюд.
    CATEGORY_CACHE_TTL: int = 600
    # Заполнить кеш меню при старте приложения.
    CACHE_WARM_UP: bool = True

    # Брокер и хранилище результатов Celery. Пусто — тот же Redis, что REDIS_URL.
    CELERY_BROKER_URL: str = ""
    # celery — PDF, email и SMS ставятся в очередь и выполняются воркером;
    # sync — выполняются прямо в запросе (так снят замер «до»).
    NOTIFICATIONS_MODE: str = "celery"
    # Имитация тяжёлых операций, секунды.
    PDF_DELAY: float = 2.0
    EMAIL_DELAY: float = 1.0
    SMS_DELAY: float = 1.0
    # Почтовый сервис «падает» на каждом N-м заказе — для демонстрации ретраев
    # и DLQ. 0 — не падает никогда.
    EMAIL_FAIL_EVERY: int = 5
    # Куда складываются сгенерированные чеки.
    RECEIPTS_DIR: str = "receipts"

    # Доставки: grpc — микросервис delivery_server.py; local — старый путь
    # прямо в таблицу deliveries (Strangler Fig: откат без деплоя).
    DELIVERY_BACKEND: str = "grpc"
    DELIVERY_GRPC_TARGET: str = "localhost:50051"
    # Сколько ждать ответа сервиса доставки, секунды. Обработчик FastAPI
    # всё это время занимает поток пула, поэтому меньше 5 с из методички.
    DELIVERY_GRPC_TIMEOUT: float = 2.0

    # Брокер событий (лабораторная № 7).
    RABBITMQ_URL: str = "amqp://sirius:sirius@localhost:5672/"
    # Как часто релей outbox проверяет новые события, секунды.
    OUTBOX_POLL_INTERVAL: float = 0.5

    @field_validator("SECRET_KEY")
    @classmethod
    def secret_key_is_long_enough(cls, value: str) -> str:
        # HS256 подписывает токен этим ключом: короткий ключ подбирается перебором.
        if len(value) < 32:
            raise ValueError("SECRET_KEY должен быть не короче 32 символов")
        return value

    @field_validator("NOTIFICATIONS_MODE")
    @classmethod
    def known_notifications_mode(cls, value: str) -> str:
        if value not in ("celery", "sync"):
            raise ValueError(f"NOTIFICATIONS_MODE должен быть celery или sync, получено {value!r}")
        return value

    @field_validator("DELIVERY_BACKEND")
    @classmethod
    def known_delivery_backend(cls, value: str) -> str:
        if value not in ("grpc", "local"):
            raise ValueError(f"DELIVERY_BACKEND должен быть grpc или local, получено {value!r}")
        return value

    @property
    def broker_url(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @field_validator("REPO_BACKEND")
    @classmethod
    def known_backend(cls, value: str) -> str:
        if value not in ("sql", "memory"):
            raise ValueError(f"REPO_BACKEND должен быть sql или memory, получено {value!r}")
        return value


settings = Settings()
