"""
Абстрактный интерфейс хранилища для модуля menu.

Про кеш интерфейс ничего не знает: закешированный и обычный репозитории
взаимозаменяемы, сервис не видит разницы.
"""
from abc import ABC, abstractmethod

from app.domain.entities import Category, CategoryMenu, MenuItem


class MenuRepository(ABC):
    @abstractmethod
    def get_item_by_id(self, item_id: int) -> MenuItem | None:
        """Блюдо по идентификатору или None."""

    @abstractmethod
    def list_items(self) -> list[MenuItem]:
        """Все блюда по возрастанию id."""

    @abstractmethod
    def get_item_by_name(self, name: str) -> MenuItem | None:
        """Блюдо по точному названию или None."""

    @abstractmethod
    def create_item(
        self, name: str, price: float, is_available: bool, category_id: int | None = None
    ) -> MenuItem:
        """Сохраняет новое блюдо и возвращает его с присвоенным id."""

    @abstractmethod
    def save_item(self, item: MenuItem) -> MenuItem:
        """Перезаписывает поля существующего блюда."""

    @abstractmethod
    def list_categories(self) -> list[Category]:
        """Все категории по возрастанию id."""

    @abstractmethod
    def get_category_menu(self, category_id: int) -> CategoryMenu | None:
        """Категория с её блюдами по возрастанию id или None."""

    @abstractmethod
    def get_category_by_name(self, name: str) -> Category | None:
        """Категория по точному названию или None."""

    @abstractmethod
    def create_category(self, name: str) -> Category:
        """Сохраняет новую категорию и возвращает её с присвоенным id."""
