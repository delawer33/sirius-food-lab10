"""
Слой бизнес-логики модуля menu. Без fastapi, sqlalchemy и redis.

Откуда приходят данные — из БД или из кеша, — сервис не знает: это решает
репозиторий, который ему передали (см. app/container.py).
"""
from dataclasses import replace

from app.domain.entities import Category, CategoryMenu, MenuItem
from app.domain.errors import BusinessRuleError, NotFoundError
from app.modules.menu.interfaces import MenuRepository


class MenuService:
    """Бизнес-правила управления меню столовой."""

    def __init__(self, repository: MenuRepository):
        self.repository = repository

    def list_items(self) -> list[MenuItem]:
        return self.repository.list_items()

    def get_item(self, item_id: int) -> MenuItem:
        item = self.repository.get_item_by_id(item_id)
        if item is None:
            raise NotFoundError("Блюдо не найдено")
        return item

    def create_item(self, name: str, price: float, category_id: int | None = None) -> MenuItem:
        """Добавляет блюдо в меню. Название должно быть уникальным."""
        if self.repository.get_item_by_name(name):
            raise BusinessRuleError("Блюдо с таким названием уже существует")
        if category_id is not None:
            self._get_category(category_id)
        # Новое блюдо сразу доступно для заказа.
        return self.repository.create_item(
            name=name, price=price, is_available=True, category_id=category_id
        )

    def update_item(
        self,
        item_id: int,
        name: str | None = None,
        price: float | None = None,
        is_available: bool | None = None,
        category_id: int | None = None,
    ) -> MenuItem:
        """Меняет переданные поля блюда, остальные оставляет как есть."""
        item = self.repository.get_item_by_id(item_id)
        if item is None:
            raise NotFoundError("Блюдо не найдено")
        if category_id is not None:
            self._get_category(category_id)

        changes = {
            "name": name,
            "price": price,
            "is_available": is_available,
            "category_id": category_id,
        }
        updated = replace(item, **{k: v for k, v in changes.items() if v is not None})
        return self.repository.save_item(updated)

    def list_categories(self) -> list[Category]:
        return self.repository.list_categories()

    def get_category_menu(self, category_id: int) -> CategoryMenu:
        return self._get_category(category_id)

    def create_category(self, name: str) -> Category:
        """Новая категория меню. Название должно быть уникальным."""
        if self.repository.get_category_by_name(name):
            raise BusinessRuleError("Категория с таким названием уже существует")
        return self.repository.create_category(name)

    def _get_category(self, category_id: int) -> CategoryMenu:
        menu = self.repository.get_category_menu(category_id)
        if menu is None:
            raise NotFoundError("Категория не найдена")
        return menu
