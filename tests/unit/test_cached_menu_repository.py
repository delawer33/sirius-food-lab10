"""
CachedMenuRepository: что кешируется, какие ключи сбрасывает каждая запись,
прогрев кеша.
"""
import json

import pytest

from app.domain.entities import MenuItem
from app.infrastructure.cache import RedisCache
from app.modules.menu.repository import CachedMenuRepository, InMemoryMenuRepository


class CountingRepository(InMemoryMenuRepository):
    """In-memory репозиторий, который считает обращения к «БД»."""

    def __init__(self, storage):
        super().__init__(storage)
        self.reads = 0

    def list_items(self):
        self.reads += 1
        return super().list_items()

    def get_category_menu(self, category_id):
        self.reads += 1
        return super().get_category_menu(category_id)


@pytest.fixture
def inner(storage):
    return CountingRepository(storage)


@pytest.fixture
def repo(inner, redis):
    return CachedMenuRepository(inner, RedisCache(redis), menu_ttl=300, category_ttl=600)


def test_menu_cached_under_menu_all_for_5_minutes(repo, inner, redis):
    inner.create_item("Борщ", 250.0, True)

    first = repo.list_items()
    second = repo.list_items()

    assert first == second == [MenuItem(1, "Борщ", 250.0, True)]
    assert inner.reads == 1
    assert json.loads(redis.get("menu:all"))[0]["name"] == "Борщ"
    assert 290 < redis.ttl("menu:all") <= 300


def test_category_cached_for_10_minutes(repo, inner, redis):
    soups = inner.create_category("Супы")

    repo.get_category_menu(soups.id)
    repo.get_category_menu(soups.id)

    assert inner.reads == 1
    assert 590 < redis.ttl(f"menu:category:{soups.id}") <= 600


def test_missing_category_cached_briefly(repo, inner, redis):
    assert repo.get_category_menu(42) is None
    assert repo.get_category_menu(42) is None

    assert inner.reads == 1
    assert redis.ttl("menu:category:42") <= 30


def test_create_item_drops_menu_and_its_category(repo, inner, redis):
    soups = inner.create_category("Супы")
    drinks = inner.create_category("Напитки")
    repo.list_items()
    repo.get_category_menu(soups.id)
    repo.get_category_menu(drinks.id)

    repo.create_item("Борщ", 250.0, True, soups.id)

    assert redis.exists("menu:all", "menu:category:1") == 0
    assert redis.exists("menu:category:2") == 1  # чужая категория не тронута


def test_moving_item_drops_both_categories(repo, inner, redis):
    inner.create_category("Супы")
    inner.create_category("Напитки")
    item = inner.create_item("Компот", 60.0, True, 1)
    repo.get_category_menu(1)
    repo.get_category_menu(2)

    repo.save_item(MenuItem(item.id, "Компот", 60.0, True, 2))

    assert redis.exists("menu:category:1", "menu:category:2") == 0


def test_create_category_drops_list_and_negative_entry(repo, redis):
    repo.list_categories()
    repo.get_category_menu(1)  # «нет такой» в кеше

    category = repo.create_category("Супы")

    assert redis.exists("menu:categories", "menu:category:1") == 0
    assert repo.get_category_menu(category.id).category == category


def test_warm_up_fills_cache_so_first_read_skips_db(repo, inner, redis):
    inner.create_category("Супы")
    inner.create_item("Борщ", 250.0, True, 1)

    assert repo.warm_up() == 3
    inner.reads = 0

    repo.list_items()
    repo.get_category_menu(1)
    repo.list_categories()
    assert inner.reads == 0


def test_invalidate_cache_drops_everything(repo, inner, redis):
    inner.create_category("Супы")
    repo.warm_up()

    repo.invalidate_cache()

    assert redis.keys("menu:*") == []
