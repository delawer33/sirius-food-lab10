"""
Зависимости FastAPI для аутентификации и проверки роли.

get_current_user отвечает на вопрос «кто ты» (401, если не удалось узнать),
require_role — «пускают ли твою роль к этому эндпоинту» (403). Проверка прав
на конкретный объект — не здесь, а в сервисах.
"""
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from app.container import get_auth_service
from app.domain.entities import User
from app.domain.errors import DomainError
from app.http_errors import to_http_exception
from app.modules.auth.service import AuthService

# Токен извлекается из заголовка Authorization: Bearer <token>. tokenUrl —
# эндпоинт, куда кнопка Authorize в Swagger отправляет логин и пароль формой.
# auto_error=False: ответ на запрос без токена формируем сами, по-русски.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    """
    Извлекает текущего пользователя из JWT.
    401 — токена нет, он невалиден или пользователя нет; 403 — пользователь заблокирован.
    """
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Требуется аутентификация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return auth_service.authenticate(token)
    except DomainError as error:
        raise to_http_exception(error)


def require_role(*roles: str):
    """
    Dependency для проверки роли пользователя.
    Возбуждает HTTPException 403, если роль не входит в разрешённые.
    """

    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Доступ запрещён для вашей роли")
        return current_user

    return checker
