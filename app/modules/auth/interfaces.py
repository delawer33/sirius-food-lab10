"""
Абстрактный интерфейс хранилища для модуля auth.
"""
from abc import ABC, abstractmethod
from datetime import datetime

from app.domain.entities import RefreshToken, User


class AuthRepository(ABC):
    @abstractmethod
    def get_user_by_id(self, user_id: int) -> User | None:
        """Пользователь по идентификатору или None."""

    @abstractmethod
    def get_user_by_email(self, email: str) -> User | None:
        """Пользователь по email или None."""

    @abstractmethod
    def save_refresh_token(self, user_id: int, token_hash: str, expires_at: datetime) -> None:
        """Запоминает выданный refresh-токен (его хеш)."""

    @abstractmethod
    def get_refresh_token(self, token_hash: str) -> RefreshToken | None:
        """Запись о refresh-токене по хешу или None."""

    @abstractmethod
    def revoke_refresh_token(self, token_id: int) -> bool:
        """
        Отзывает токен. Возвращает True, если он был активен, и False, если его
        уже отозвали. Проверка и отзыв атомарны: из двух одновременных запросов
        с одним токеном True получит только один.
        """

    @abstractmethod
    def revoke_all_sessions(self, user_id: int) -> None:
        """Отзывает все refresh-токены пользователя и увеличивает token_version."""
