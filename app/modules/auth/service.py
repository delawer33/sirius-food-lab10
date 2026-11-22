"""
Слой бизнес-логики модуля auth: вход, проверка access-токена, ротация
refresh-токенов, выход. Без fastapi и sqlalchemy.
"""
import hashlib
from dataclasses import dataclass

from app.core.jwt import (
    ACCESS,
    REFRESH,
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    expires_at,
)
from app.core.security import DUMMY_HASH, verify_password
from app.domain.entities import User
from app.domain.errors import AccessDeniedError, AuthenticationError
from app.modules.auth.interfaces import AuthRepository


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


def hash_token(token: str) -> str:
    """
    SHA-256 от refresh-токена. bcrypt здесь не нужен: токен — случайная строка
    большой длины, перебирать её по хешу бессмысленно, а искать по хешу надо быстро.
    """
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    """Аутентификация: кто делает запрос."""

    def __init__(self, repository: AuthRepository):
        self.repository = repository

    def login(self, email: str, password: str) -> TokenPair:
        """Проверяет email и пароль и выдаёт пару токенов."""
        user = self.repository.get_user_by_email(email)
        # Хеш проверяется и для несуществующего email: время ответа одинаковое.
        password_ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
        if user is None or not password_ok:
            # Одно сообщение для обоих случаев: по ответу не узнать, есть ли такой email.
            raise AuthenticationError("Неверный email или пароль")
        self._ensure_active(user)
        return self._issue_tokens(user)

    def authenticate(self, access_token: str) -> User:
        """Возвращает владельца access-токена. Используется в get_current_user."""
        try:
            payload = decode_token(access_token, ACCESS)
        except InvalidTokenError:
            raise AuthenticationError("Недействительный токен")
        user = self.repository.get_user_by_id(int(payload["sub"]))
        if user is None or payload["ver"] != user.token_version:
            raise AuthenticationError("Недействительный токен")
        self._ensure_active(user)
        return user

    def refresh(self, refresh_token: str) -> TokenPair:
        """
        Refresh Token rotation: старый токен отзывается, выдаётся новая пара.
        Повторное предъявление отозванного токена означает, что его украли:
        тогда завершаются все сессии пользователя.
        """
        try:
            payload = decode_token(refresh_token, REFRESH)
        except InvalidTokenError:
            raise AuthenticationError("Недействительный refresh-токен")

        record = self.repository.get_refresh_token(hash_token(refresh_token))
        user = self.repository.get_user_by_id(record.user_id) if record else None
        # Токен из поколения, которое уже сброшено, просто не принимается.
        # Повторный сброс здесь не нужен: иначе украденный старый токен
        # позволял бы раз за разом выкидывать пользователя из новых сессий.
        if user is None or payload["ver"] != user.token_version:
            raise AuthenticationError("Недействительный refresh-токен")

        if not self.repository.revoke_refresh_token(record.id):
            self.repository.revoke_all_sessions(user.id)
            raise AuthenticationError(
                "Refresh-токен уже использован. Все сессии завершены, войдите заново"
            )

        self._ensure_active(user)
        return self._issue_tokens(user)

    def logout(self, refresh_token: str) -> None:
        """Отзывает refresh-токен. Access-токен доживёт свои 15 минут."""
        try:
            decode_token(refresh_token, REFRESH)
        except InvalidTokenError:
            raise AuthenticationError("Недействительный refresh-токен")
        record = self.repository.get_refresh_token(hash_token(refresh_token))
        if record is not None:
            self.repository.revoke_refresh_token(record.id)

    def _issue_tokens(self, user: User) -> TokenPair:
        access = create_access_token(user.id, user.token_version)
        refresh = create_refresh_token(user.id, user.token_version)
        # Запоминаем refresh-токен, чтобы его можно было отозвать.
        self.repository.save_refresh_token(
            user.id, hash_token(refresh), expires_at(refresh)
        )
        return TokenPair(access_token=access, refresh_token=refresh)

    @staticmethod
    def _ensure_active(user: User) -> None:
        if user.is_blocked:
            raise AccessDeniedError("Пользователь заблокирован")
