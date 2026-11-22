"""
Абстрактный интерфейс хранилища для модуля users.
"""
from abc import ABC, abstractmethod

from app.domain.entities import User


class UserRepository(ABC):
    @abstractmethod
    def get_user_by_id(self, user_id: int) -> User | None:
        """Пользователь по идентификатору или None."""

    @abstractmethod
    def get_user_by_email(self, email: str) -> User | None:
        """Пользователь по email или None."""

    @abstractmethod
    def create_user(
        self,
        email: str,
        phone: str | None,
        balance: float,
        is_blocked: bool,
        role: str,
        password_hash: str,
    ) -> User:
        """Сохраняет нового пользователя и возвращает его с присвоенным id."""

    @abstractmethod
    def update_balance(self, user_id: int, new_balance: float) -> float:
        """Записывает новый баланс и возвращает сохранённое значение."""

    @abstractmethod
    def set_role(self, user_id: int, role: str) -> User:
        """Назначает пользователю роль."""

    @abstractmethod
    def set_blocked(self, user_id: int, is_blocked: bool) -> User:
        """Блокирует или разблокирует пользователя."""
