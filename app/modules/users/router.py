"""
Транспортный слой модуля users.
"""
from fastapi import APIRouter, Depends, HTTPException

from app.container import get_user_service
from app.core.dependencies import get_current_user, require_role
from app.core.rate_limit import rate_limit
from app.domain.entities import User
from app.domain.errors import DomainError
from app.domain.roles import ADMIN
from app.http_errors import to_http_exception
from app.modules.users.service import UserService
from app.schemas import BlockUpdate, RoleUpdate, UserCreate, UserProfile

router = APIRouter()


@router.post("/register", dependencies=[Depends(rate_limit(max_requests=5, window=60))])
def register_user(
    payload: UserCreate,
    service: UserService = Depends(get_user_service),
):
    # Формат email проверяет Pydantic (EmailStr), формат телефона — здесь.
    # Уникальность email — бизнес-правило, она проверяется в сервисе.
    if payload.phone and len(payload.phone) < 10:
        raise HTTPException(
            status_code=400,
            detail="Некорректный формат номера телефона",
        )

    try:
        user = service.register(email=payload.email, password=payload.password, phone=payload.phone)
    except DomainError as error:
        raise to_http_exception(error)

    return {"status": "success", "user_id": user.id, "email": user.email}


@router.get("/me", response_model=UserProfile)
def read_me(current_user: User = Depends(get_current_user)):
    """Профиль владельца токена."""
    return current_user


@router.post("/{user_id}/topup")
def top_up_balance(
    user_id: int,
    amount: float,
    current_user: User = Depends(get_current_user),
    service: UserService = Depends(get_user_service),
):
    # Техническая проверка положительности суммы пополнения.
    if amount <= 0:
        raise HTTPException(
            status_code=400,
            detail="Сумма пополнения должна быть положительной",
        )

    try:
        new_balance = service.top_up(user_id=user_id, amount=amount, actor=current_user)
    except DomainError as error:
        raise to_http_exception(error)

    return {"status": "success", "new_balance": new_balance}


@router.patch("/{user_id}/role", response_model=UserProfile)
def change_role(
    user_id: int,
    payload: RoleUpdate,
    current_user: User = Depends(require_role(ADMIN)),
    service: UserService = Depends(get_user_service),
):
    """Назначить роль. Только для администратора."""
    try:
        return service.change_role(user_id, payload.role, actor=current_user)
    except DomainError as error:
        raise to_http_exception(error)


@router.patch("/{user_id}/block", response_model=UserProfile)
def set_blocked(
    user_id: int,
    payload: BlockUpdate,
    current_user: User = Depends(require_role(ADMIN)),
    service: UserService = Depends(get_user_service),
):
    """Заблокировать или разблокировать пользователя. Только для администратора."""
    try:
        return service.set_blocked(user_id, payload.is_blocked, actor=current_user)
    except DomainError as error:
        raise to_http_exception(error)
