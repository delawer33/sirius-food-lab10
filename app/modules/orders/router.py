"""
Транспортный слой модуля orders (круг 4: Frameworks & Drivers).

Принимает HTTP-запрос, делает техническую валидацию, получает готовый
сервис из app.container (там выбирается реализация репозитория), вызывает его
и переводит доменные исключения в HTTP-статусы.

Роль проверяется здесь (require_role), права на конкретный заказ — в сервисе.
"""
import time

import structlog
from fastapi import APIRouter, Depends, HTTPException

from app.container import get_order_service
from app.core.dependencies import get_current_user, require_role
from app.core.rate_limit import rate_limit
from app.domain.entities import User
from app.domain.errors import DomainError
from app.domain.roles import ADMIN, COOK, STUDENT
from app.http_errors import to_http_exception
from app.modules.orders.service import OrderService
from app.schemas import OrderCreate, OrderResponse
from observability.metrics import ORDERS_CREATED

logger = structlog.get_logger()

router = APIRouter()
kitchen_router = APIRouter()


@router.post("/create", dependencies=[Depends(rate_limit(max_requests=10, window=60))])
def create_order(
    payload: OrderCreate,
    current_user: User = Depends(require_role(STUDENT)),
    service: OrderService = Depends(get_order_service),
):
    # Техническая валидация уровня транспортного протокола.
    if payload.quantity <= 0:
        raise HTTPException(
            status_code=400,
            detail="Количество должно быть больше нуля",
        )

    started = time.perf_counter()
    try:
        order_id = service.create_order(
            user_id=current_user.id,
            item_id=payload.item_id,
            quantity=payload.quantity,
        )
    except DomainError as error:
        logger.info("order_rejected", user_id=current_user.id, item_id=payload.item_id, reason=str(error))
        raise to_http_exception(error)

    ORDERS_CREATED.inc()
    # correlation_id добавится из контекста запроса.
    logger.info(
        "order_created",
        order_id=order_id,
        user_id=current_user.id,
        item_id=payload.item_id,
        quantity=payload.quantity,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return {"status": "success", "order_id": order_id}


@router.get("/my", response_model=list[OrderResponse])
def my_orders(
    current_user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    return service.list_my_orders(current_user)


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    try:
        return service.get_order(order_id, current_user)
    except DomainError as error:
        raise to_http_exception(error)


@router.post("/{order_id}/cancel")
def cancel_order(
    order_id: int,
    current_user: User = Depends(get_current_user),
    service: OrderService = Depends(get_order_service),
):
    try:
        service.cancel_order(order_id, current_user)
    except DomainError as error:
        raise to_http_exception(error)
    return {"status": "success"}


kitchen_staff = require_role(COOK, ADMIN)


@kitchen_router.get("/orders", response_model=list[OrderResponse], dependencies=[Depends(kitchen_staff)])
def kitchen_orders(service: OrderService = Depends(get_order_service)):
    """Очередь кухни. Только повар и администратор."""
    return service.get_kitchen_orders()


@kitchen_router.post("/orders/{order_id}/ready", dependencies=[Depends(kitchen_staff)])
def mark_ready(order_id: int, service: OrderService = Depends(get_order_service)):
    """Заказ приготовлен, его можно отдавать курьеру."""
    try:
        service.mark_ready(order_id)
    except DomainError as error:
        raise to_http_exception(error)
    return {"status": "success"}
