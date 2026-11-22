"""
Корень композиции (composition root): единственное место, где решается,
какая реализация репозитория попадёт в сервис.

Реализация выбирается настройкой REPO_BACKEND:
  sql    — SQLAlchemy, база по DATABASE_URL (по умолчанию);
  memory — хранилище в памяти процесса, данные живут до перезапуска.
Смена хранилища не требует правок ни в service.py, ни в router.py.

Доставки — отдельный микросервис: сервис получает шлюз DeliveryGateway,
реализацию выбирает DELIVERY_BACKEND.

Здесь же меню оборачивается кешем: при CACHE_ENABLED сервис получает
CachedMenuRepository поверх обычного репозитория.
"""
import logging

from fastapi import Depends
from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import get_redis, redis_client
from app.database import SessionLocal, get_db
from app.infrastructure.cache import RedisCache
from app.infrastructure.memory import InMemoryStorage
from app.infrastructure.notifications import CeleryOrderNotifier, SyncOrderNotifier
from app.modules.auth.repository import InMemoryAuthRepository, SqlAlchemyAuthRepository
from app.modules.auth.service import AuthService
from app.infrastructure.delivery_grpc import GrpcDeliveryGateway, get_channel
from app.modules.delivery.interfaces import DeliveryGateway
from app.modules.delivery.repository import (
    InMemoryDeliveryGateway,
    InMemoryDeliveryRepository,
    SqlAlchemyDeliveryGateway,
    SqlAlchemyDeliveryRepository,
)
from app.modules.delivery.service import DeliveryService
from app.modules.menu.interfaces import MenuRepository
from app.modules.menu.repository import (
    CachedMenuRepository,
    InMemoryMenuRepository,
    SqlAlchemyMenuRepository,
)
from app.modules.menu.service import MenuService
from app.modules.orders.interfaces import OrderNotifier
from app.modules.orders.repository import InMemoryOrderRepository, SqlAlchemyOrderRepository
from app.modules.orders.service import OrderService
from app.modules.users.repository import InMemoryUserRepository, SqlAlchemyUserRepository
from app.modules.users.service import UserService

logger = logging.getLogger(__name__)

REPO_BACKEND = settings.REPO_BACKEND
CACHE_ENABLED = settings.CACHE_ENABLED

memory_storage = InMemoryStorage()


def get_order_notifier() -> OrderNotifier:
    """Фоновые задачи через Celery или та же работа прямо в запросе (NOTIFICATIONS_MODE)."""
    if settings.NOTIFICATIONS_MODE == "sync":
        return SyncOrderNotifier()
    return CeleryOrderNotifier()


def get_order_service(
    db: Session = Depends(get_db), notifier: OrderNotifier = Depends(get_order_notifier)
) -> OrderService:
    if REPO_BACKEND == "memory":
        return OrderService(InMemoryOrderRepository(memory_storage), notifier)
    return OrderService(SqlAlchemyOrderRepository(db), notifier)


def get_user_service(db: Session = Depends(get_db)) -> UserService:
    if REPO_BACKEND == "memory":
        return UserService(InMemoryUserRepository(memory_storage))
    return UserService(SqlAlchemyUserRepository(db))


def build_menu_repository(db: Session, redis: Redis) -> MenuRepository:
    if REPO_BACKEND == "memory":
        repository: MenuRepository = InMemoryMenuRepository(memory_storage)
    else:
        repository = SqlAlchemyMenuRepository(db)
    if not CACHE_ENABLED:
        return repository
    return CachedMenuRepository(
        repository,
        RedisCache(redis),
        menu_ttl=settings.MENU_CACHE_TTL,
        category_ttl=settings.CATEGORY_CACHE_TTL,
    )


def get_menu_service(
    db: Session = Depends(get_db), redis: Redis = Depends(get_redis)
) -> MenuService:
    return MenuService(build_menu_repository(db, redis))


def warm_up_cache() -> None:
    """
    Прогрев кеша меню при старте приложения. Если БД или Redis недоступны,
    приложение всё равно стартует: кеш заполнится при первых запросах.
    """
    if not CACHE_ENABLED:
        return
    try:
        with SessionLocal() as db:
            repository = build_menu_repository(db, redis_client)
            keys = repository.warm_up()
        logger.info("Кеш меню прогрет: %s ключей", keys)
    except Exception:
        logger.exception("Не удалось прогреть кеш меню")


def get_delivery_gateway(db: Session = Depends(get_db)) -> DeliveryGateway:
    """Доставки: микросервис по gRPC, старый путь в БД (DELIVERY_BACKEND=local) или память."""
    if REPO_BACKEND == "memory":
        return InMemoryDeliveryGateway(memory_storage)
    if settings.DELIVERY_BACKEND == "local":
        return SqlAlchemyDeliveryGateway(db)
    return GrpcDeliveryGateway(get_channel(settings.DELIVERY_GRPC_TARGET), settings.DELIVERY_GRPC_TIMEOUT)


def get_delivery_service(
    db: Session = Depends(get_db),
    gateway: DeliveryGateway = Depends(get_delivery_gateway),
) -> DeliveryService:
    if REPO_BACKEND == "memory":
        return DeliveryService(InMemoryDeliveryRepository(memory_storage), gateway)
    return DeliveryService(SqlAlchemyDeliveryRepository(db), gateway)


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    if REPO_BACKEND == "memory":
        return AuthService(InMemoryAuthRepository(memory_storage))
    return AuthService(SqlAlchemyAuthRepository(db))
