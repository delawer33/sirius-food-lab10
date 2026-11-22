"""
Контракт MenuRepository для трёх реализаций: SQLAlchemy, in-memory и
CachedMenuRepository поверх SQLAlchemy. Кеширующий репозиторий обязан
вести себя как обычный — иначе сервис заметил бы, что данные из Redis.
"""
import pytest

from app.domain.entities import Category, CategoryMenu, MenuItem
from app.infrastructure.cache import RedisCache
from app.modules.menu.repository import (
    CachedMenuRepository,
    InMemoryMenuRepository,
    SqlAlchemyMenuRepository,
)


@pytest.fixture(params=["sql", "memory", "cached"])
def menu(request, db_session, storage, redis):
    if request.param == "memory":
        return InMemoryMenuRepository(storage)
    repository = SqlAlchemyMenuRepository(db_session)
    if request.param == "cached":
        return CachedMenuRepository(repository, RedisCache(redis), menu_ttl=300, category_ttl=600)
    return repository


def test_categories_create_and_lookup(menu):
    soups = menu.create_category("Супы")
    drinks = menu.create_category("Напитки")

    assert (soups, drinks) == (Category(1, "Супы"), Category(2, "Напитки"))
    assert menu.list_categories() == [soups, drinks]
    assert menu.get_category_by_name("Напитки") == drinks
    assert menu.get_category_by_name("Десерты") is None


def test_category_menu_contains_only_its_items(menu):
    soups = menu.create_category("Супы")
    menu.create_category("Напитки")
    borscht = menu.create_item("Борщ", 250.0, True, soups.id)
    menu.create_item("Компот", 60.0, True, 2)
    menu.create_item("Хлеб", 10.0, True)

    assert menu.get_category_menu(soups.id) == CategoryMenu(soups, [borscht])
    assert menu.get_category_menu(999) is None


def test_reads_see_writes(menu):
    """Каждое чтение видит предыдущую запись — в том числе через кеш."""
    soups = menu.create_category("Супы")
    drinks = menu.create_category("Напитки")
    assert menu.list_items() == []
    assert menu.get_category_menu(drinks.id).items == []

    item = menu.create_item("Компот", 60.0, True, soups.id)
    assert menu.list_items() == [item]
    assert menu.get_category_menu(soups.id).items == [item]

    moved = menu.save_item(MenuItem(item.id, "Компот", 70.0, False, drinks.id))
    assert menu.list_items() == [moved]
    assert menu.get_category_menu(soups.id).items == []
    assert menu.get_category_menu(drinks.id).items == [moved]

    assert menu.get_category_menu(3) is None
    desserts = menu.create_category("Десерты")
    assert menu.get_category_menu(3) == CategoryMenu(desserts, [])
    assert menu.list_categories() == [soups, drinks, desserts]
