"""
Инфраструктурный слой модуля menu (круг 3: Interface Adapters).

SqlAlchemyMenuRepository и InMemoryMenuRepository реализуют MenuRepository.
CachedMenuRepository — тоже MenuRepository: оборачивает любой из них и
кеширует чтение меню в Redis (Cache-Aside). Кеш — деталь хранения, поэтому
он здесь, а не в сервисе.
"""
import json
from dataclasses import asdict, replace

from sqlalchemy.orm import Session, contains_eager

from app.domain.entities import Category, CategoryMenu, MenuItem
from app.infrastructure.cache import RedisCache
from app.infrastructure.memory import InMemoryStorage
from app.models import Category as CategoryModel
from app.models import MenuItem as MenuItemModel
from app.modules.menu.interfaces import MenuRepository


def _to_entity(row: MenuItemModel) -> MenuItem:
    return MenuItem(
        id=row.id,
        name=row.name,
        price=row.price,
        is_available=row.is_available,
        category_id=row.category_id,
    )


def _category_to_entity(row: CategoryModel) -> Category:
    return Category(id=row.id, name=row.name)


class SqlAlchemyMenuRepository(MenuRepository):
    def __init__(self, db: Session):
        self.db = db

    def get_item_by_id(self, item_id: int) -> MenuItem | None:
        row = self.db.get(MenuItemModel, item_id)
        return _to_entity(row) if row else None

    def list_items(self) -> list[MenuItem]:
        return [_to_entity(row) for row in self.db.query(MenuItemModel).order_by(MenuItemModel.id)]

    def get_item_by_name(self, name: str) -> MenuItem | None:
        row = self.db.query(MenuItemModel).filter(MenuItemModel.name == name).first()
        return _to_entity(row) if row else None

    def create_item(
        self, name: str, price: float, is_available: bool, category_id: int | None = None
    ) -> MenuItem:
        row = MenuItemModel(
            name=name, price=price, is_available=is_available, category_id=category_id
        )
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return _to_entity(row)

    def save_item(self, item: MenuItem) -> MenuItem:
        row = self.db.get(MenuItemModel, item.id)
        row.name = item.name
        row.price = item.price
        row.is_available = item.is_available
        row.category_id = item.category_id
        self.db.commit()
        self.db.refresh(row)
        return _to_entity(row)

    def list_categories(self) -> list[Category]:
        rows = self.db.query(CategoryModel).order_by(CategoryModel.id)
        return [_category_to_entity(row) for row in rows]

    def get_category_menu(self, category_id: int) -> CategoryMenu | None:
        category = self.db.get(CategoryModel, category_id)
        if category is None:
            return None
        # Один запрос с JOIN: блюда вместе с категорией.
        rows = (
            self.db.query(MenuItemModel)
            .join(MenuItemModel.category)
            .options(contains_eager(MenuItemModel.category))
            .filter(CategoryModel.id == category_id)
            .order_by(MenuItemModel.id)
        )
        return CategoryMenu(_category_to_entity(category), [_to_entity(row) for row in rows])

    def get_category_by_name(self, name: str) -> Category | None:
        row = self.db.query(CategoryModel).filter(CategoryModel.name == name).first()
        return _category_to_entity(row) if row else None

    def create_category(self, name: str) -> Category:
        row = CategoryModel(name=name)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return _category_to_entity(row)


class InMemoryMenuRepository(MenuRepository):
    def __init__(self, storage: InMemoryStorage):
        self.storage = storage

    def get_item_by_id(self, item_id: int) -> MenuItem | None:
        item = self.storage.menu_items.get(item_id)
        return replace(item) if item else None

    def list_items(self) -> list[MenuItem]:
        return [replace(item) for _, item in sorted(self.storage.menu_items.items())]

    def get_item_by_name(self, name: str) -> MenuItem | None:
        item = next((i for i in self.storage.menu_items.values() if i.name == name), None)
        return replace(item) if item else None

    def create_item(
        self, name: str, price: float, is_available: bool, category_id: int | None = None
    ) -> MenuItem:
        with self.storage.lock:
            item_id = self.storage.next_id(self.storage.menu_items)
            item = MenuItem(item_id, name, price, is_available, category_id)
            self.storage.menu_items[item_id] = item
            return replace(item)

    def save_item(self, item: MenuItem) -> MenuItem:
        with self.storage.lock:
            self.storage.menu_items[item.id] = replace(item)
            return replace(item)

    def list_categories(self) -> list[Category]:
        return [replace(c) for _, c in sorted(self.storage.categories.items())]

    def get_category_menu(self, category_id: int) -> CategoryMenu | None:
        category = self.storage.categories.get(category_id)
        if category is None:
            return None
        items = [
            replace(i)
            for _, i in sorted(self.storage.menu_items.items())
            if i.category_id == category_id
        ]
        return CategoryMenu(replace(category), items)

    def get_category_by_name(self, name: str) -> Category | None:
        category = next((c for c in self.storage.categories.values() if c.name == name), None)
        return replace(category) if category else None

    def create_category(self, name: str) -> Category:
        with self.storage.lock:
            category_id = self.storage.next_id(self.storage.categories)
            category = Category(category_id, name)
            self.storage.categories[category_id] = category
            return replace(category)


# --- Кеш -----------------------------------------------------------------------

MENU_ALL_KEY = "menu:all"
CATEGORIES_KEY = "menu:categories"
# Несуществующая категория кешируется ненадолго: иначе запросы к случайным
# id всегда шли бы мимо кеша в БД.
MISSING_CATEGORY_TTL = 30


def category_key(category_id: int) -> str:
    return f"menu:category:{category_id}"


def _dump_items(items: list[MenuItem]) -> str:
    return json.dumps([asdict(item) for item in items], ensure_ascii=False)


def _load_items(data: str) -> list[MenuItem]:
    return [MenuItem(**item) for item in json.loads(data)]


def _dump_categories(categories: list[Category]) -> str:
    return json.dumps([asdict(c) for c in categories], ensure_ascii=False)


def _load_categories(data: str) -> list[Category]:
    return [Category(**c) for c in json.loads(data)]


def _dump_category_menu(menu: CategoryMenu | None) -> str:
    return json.dumps(asdict(menu) if menu else None, ensure_ascii=False)


def _load_category_menu(data: str) -> CategoryMenu | None:
    raw = json.loads(data)
    if raw is None:
        return None
    return CategoryMenu(Category(**raw["category"]), [MenuItem(**i) for i in raw["items"]])


class CachedMenuRepository(MenuRepository):
    """
    Cache-Aside поверх другого MenuRepository.

    Кешируется то, что читают все и часто: всё меню (menu:all), список
    категорий (menu:categories) и категория с блюдами (menu:category:{id}).
    Точечные чтения по id и названию идут в БД: ими пользуются запись и
    проверки при заказе, им нужны свежие данные.

    Инвалидация событийная: каждая запись через этот репозиторий удаляет
    затронутые ключи сразу после коммита в БД. TTL — страховка на случай,
    если данные поменяли в обход приложения.
    """

    def __init__(
        self, inner: MenuRepository, cache: RedisCache, menu_ttl: int, category_ttl: int
    ):
        self.inner = inner
        self.cache = cache
        self.menu_ttl = menu_ttl
        self.category_ttl = category_ttl

    # Чтение через кеш

    def list_items(self) -> list[MenuItem]:
        return self.cache.get_or_load(
            MENU_ALL_KEY, self.menu_ttl, self.inner.list_items, _dump_items, _load_items
        )

    def list_categories(self) -> list[Category]:
        return self.cache.get_or_load(
            CATEGORIES_KEY,
            self.category_ttl,
            self.inner.list_categories,
            _dump_categories,
            _load_categories,
        )

    def get_category_menu(self, category_id: int) -> CategoryMenu | None:
        key = category_key(category_id)
        menu = self.cache.get_or_load(
            key,
            self.category_ttl,
            lambda: self.inner.get_category_menu(category_id),
            _dump_category_menu,
            _load_category_menu,
        )
        if menu is None:
            # Пустой ответ живёт меньше, чем настоящая категория.
            self.cache.put(key, MISSING_CATEGORY_TTL, _dump_category_menu(None))
        return menu

    # Чтение без кеша

    def get_item_by_id(self, item_id: int) -> MenuItem | None:
        return self.inner.get_item_by_id(item_id)

    def get_item_by_name(self, name: str) -> MenuItem | None:
        return self.inner.get_item_by_name(name)

    def get_category_by_name(self, name: str) -> Category | None:
        return self.inner.get_category_by_name(name)

    # Запись: сначала БД, потом сброс кеша

    def create_item(
        self, name: str, price: float, is_available: bool, category_id: int | None = None
    ) -> MenuItem:
        item = self.inner.create_item(name, price, is_available, category_id)
        self.cache.delete(*self._keys_for_items(item))
        return item

    def save_item(self, item: MenuItem) -> MenuItem:
        # Блюдо могло переехать в другую категорию: сбросить надо обе.
        before = self.inner.get_item_by_id(item.id)
        saved = self.inner.save_item(item)
        self.cache.delete(*self._keys_for_items(before, saved))
        return saved

    def create_category(self, name: str) -> Category:
        category = self.inner.create_category(name)
        # category_key — на случай, если этот id запрашивали, пока его не было.
        self.cache.delete(CATEGORIES_KEY, category_key(category.id))
        return category

    def invalidate_cache(self) -> None:
        """Сбросить всё меню. Для ручного вызова, например после правки БД."""
        keys = [category_key(c.id) for c in self.inner.list_categories()]
        self.cache.delete(MENU_ALL_KEY, CATEGORIES_KEY, *keys)

    def warm_up(self) -> int:
        """
        Прогрев: заполнить кеш из БД при старте приложения, чтобы первые
        запросы после деплоя не шли в базу все разом. Возвращает число ключей.
        """
        self.cache.put(MENU_ALL_KEY, self.menu_ttl, _dump_items(self.inner.list_items()))
        categories = self.inner.list_categories()
        self.cache.put(CATEGORIES_KEY, self.category_ttl, _dump_categories(categories))
        for category in categories:
            menu = self.inner.get_category_menu(category.id)
            self.cache.put(category_key(category.id), self.category_ttl, _dump_category_menu(menu))
        return 2 + len(categories)

    @staticmethod
    def _keys_for_items(*items: MenuItem | None) -> list[str]:
        keys = {MENU_ALL_KEY}
        keys.update(category_key(i.category_id) for i in items if i and i.category_id)
        return sorted(keys)
