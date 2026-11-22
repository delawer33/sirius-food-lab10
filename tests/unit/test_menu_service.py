"""
Unit-тесты MenuService без СУБД.
"""
import pytest

from app.domain.entities import Category, MenuItem
from app.domain.errors import BusinessRuleError, NotFoundError
from app.modules.menu.repository import InMemoryMenuRepository
from app.modules.menu.service import MenuService

BORSCHT = MenuItem(id=1, name="Борщ", price=250.0, is_available=True)


@pytest.fixture
def service(storage):
    return MenuService(InMemoryMenuRepository(storage))


def test_create_item_is_available_by_default(service):
    item = service.create_item("Компот", 60.0)

    assert (item.id, item.is_available) == (1, True)


def test_create_item_rejects_duplicate_name(service, storage):
    storage.menu_items[1] = BORSCHT

    with pytest.raises(BusinessRuleError, match="уже существует"):
        service.create_item("Борщ", 300.0)


def test_update_changes_only_passed_fields(service, storage):
    storage.menu_items[1] = BORSCHT

    service.update_item(1, is_available=False)

    assert storage.menu_items[1] == MenuItem(1, "Борщ", 250.0, False)


def test_update_unknown_item(service):
    with pytest.raises(NotFoundError, match="Блюдо не найдено"):
        service.update_item(1, price=10.0)


def test_create_item_in_category(service, storage):
    storage.categories[1] = Category(1, "Супы")

    item = service.create_item("Борщ", 250.0, category_id=1)

    assert item.category_id == 1
    assert service.get_category_menu(1).items == [item]


def test_create_item_in_unknown_category(service):
    with pytest.raises(NotFoundError, match="Категория не найдена"):
        service.create_item("Борщ", 250.0, category_id=9)


def test_move_item_to_unknown_category(service, storage):
    storage.menu_items[1] = BORSCHT

    with pytest.raises(NotFoundError, match="Категория не найдена"):
        service.update_item(1, category_id=9)


def test_create_category_rejects_duplicate_name(service, storage):
    storage.categories[1] = Category(1, "Супы")

    with pytest.raises(BusinessRuleError, match="уже существует"):
        service.create_category("Супы")


# --- Добавлено по итогам mutmut (ЛР № 10) ------------------------------------
# get_item появился в ЛР № 8 для витрины и проверялся только через API.

def test_get_item_returns_item(service, storage):
    storage.menu_items[1] = BORSCHT

    assert service.get_item(1) == BORSCHT


def test_get_unknown_item_is_not_found(service):
    with pytest.raises(NotFoundError, match="Блюдо не найдено"):
        service.get_item(999)


def test_create_item_saves_name_and_price(service, storage):
    item = service.create_item("Компот", 60.0)

    assert storage.menu_items[item.id] == MenuItem(item.id, "Компот", 60.0, True)


def test_update_changes_every_passed_field(service, storage):
    storage.menu_items[1] = BORSCHT
    category = service.create_category("Супы")

    service.update_item(1, name="Щи", price=200.0, is_available=False, category_id=category.id)

    assert storage.menu_items[1] == MenuItem(1, "Щи", 200.0, False, category.id)


def test_create_category_saves_name(service):
    category = service.create_category("Супы")

    assert [c.name for c in service.list_categories()] == ["Супы"]
    assert category.name == "Супы"
