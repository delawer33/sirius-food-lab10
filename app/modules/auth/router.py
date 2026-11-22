"""
Транспортный слой модуля auth.

/auth/login принимает JSON, /auth/token — форму OAuth2 (username = email):
её отправляет кнопка Authorize в Swagger. Лимит попыток у них общий.
"""
from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.container import get_auth_service
from app.core.rate_limit import rate_limit
from app.domain.errors import DomainError
from app.http_errors import to_http_exception
from app.modules.auth.service import AuthService
from app.schemas import LoginSchema, RefreshSchema, TokenResponse

router = APIRouter()

login_limit = rate_limit(max_requests=5, window=60, scope="login")


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(login_limit)],
)
def login(payload: LoginSchema, service: AuthService = Depends(get_auth_service)):
    """Аутентификация пользователя и выдача пары токенов."""
    try:
        return service.login(payload.email, payload.password)
    except DomainError as error:
        raise to_http_exception(error)


@router.post(
    "/token",
    response_model=TokenResponse,
    dependencies=[Depends(login_limit)],
)
def login_form(
    form: OAuth2PasswordRequestForm = Depends(),
    service: AuthService = Depends(get_auth_service),
):
    """То же, что /auth/login, но формой OAuth2. Для кнопки Authorize в Swagger."""
    try:
        return service.login(form.username, form.password)
    except DomainError as error:
        raise to_http_exception(error)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit(max_requests=10, window=60))],
)
def refresh(payload: RefreshSchema, service: AuthService = Depends(get_auth_service)):
    """Новая пара токенов в обмен на refresh-токен. Старый refresh-токен сгорает."""
    try:
        return service.refresh(payload.refresh_token)
    except DomainError as error:
        raise to_http_exception(error)


@router.post("/logout")
def logout(payload: RefreshSchema, service: AuthService = Depends(get_auth_service)):
    """Отзывает refresh-токен."""
    try:
        service.logout(payload.refresh_token)
    except DomainError as error:
        raise to_http_exception(error)
    return {"status": "success"}
