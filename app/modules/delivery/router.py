"""
Транспортный слой модуля delivery.
"""
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.container import get_delivery_service
from app.core.dependencies import get_current_user, require_role
from app.domain.entities import User
from app.domain.errors import DomainError
from app.domain.roles import ADMIN, COURIER
from app.http_errors import to_http_exception
from app.modules.delivery.service import DeliveryService
from app.schemas import DeliveryAssign, DeliveryResponse

router = APIRouter()


@router.post("/assign", dependencies=[Depends(require_role(ADMIN))])
def assign_courier(
    payload: DeliveryAssign,
    service: DeliveryService = Depends(get_delivery_service),
):
    """Назначить курьера на готовый заказ. Только для администратора."""
    try:
        delivery = service.assign_courier(payload.order_id, payload.courier_id)
    except DomainError as error:
        raise to_http_exception(error)
    return {"status": "success", "delivery_id": delivery.id}


@router.get("/my", response_model=list[DeliveryResponse])
def my_deliveries(
    current_user: User = Depends(require_role(COURIER)),
    service: DeliveryService = Depends(get_delivery_service),
):
    """Доставки текущего курьера. Чужих курьер не видит."""
    try:
        return service.list_my_deliveries(current_user)
    except DomainError as error:
        raise to_http_exception(error)


@router.get("/{delivery_id}", response_model=DeliveryResponse)
def get_delivery(
    delivery_id: int,
    current_user: User = Depends(get_current_user),
    service: DeliveryService = Depends(get_delivery_service),
):
    try:
        return service.get_delivery(delivery_id, current_user)
    except DomainError as error:
        raise to_http_exception(error)


@router.get("/{delivery_id}/track")
def track_delivery(
    delivery_id: int,
    current_user: User = Depends(get_current_user),
    service: DeliveryService = Depends(get_delivery_service),
):
    """
    Статусы доставки в реальном времени (Server-Sent Events), из потока
    TrackDelivery сервиса доставки. `curl -N` покажет их по мере прихода.
    """
    try:
        statuses = service.track_delivery(delivery_id, current_user)
        # Первый статус — до ответа: если сервис недоступен, клиент получит
        # 503, а не 200 с ошибкой внутри потока.
        first = next(statuses, None)
    except DomainError as error:
        raise to_http_exception(error)

    def events():
        if first is None:
            return
        yield f"data: {first}\n\n"
        try:
            for status in statuses:
                yield f"data: {status}\n\n"
        except DomainError as error:
            yield f"event: error\ndata: {error.message}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.patch("/{delivery_id}/complete")
def complete_delivery(
    delivery_id: int,
    current_user: User = Depends(require_role(COURIER, ADMIN)),
    service: DeliveryService = Depends(get_delivery_service),
):
    try:
        service.complete_delivery(delivery_id, current_user)
    except DomainError as error:
        raise to_http_exception(error)
    return {"status": "success"}
