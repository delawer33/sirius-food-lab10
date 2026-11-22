"""
Меню для нагрузочного теста: категории и блюда в них.

    python -m scripts.seed_menu                 # 10 категорий по 20 блюд
    python -m scripts.seed_menu --categories 5 --items 40

Пишет прямо в БД через репозиторий, без кеша: кеш сбрасывается отдельно
(или просто истекает), а замер «до» идёт с CACHE_ENABLED=False.
"""
import argparse

from app.database import SessionLocal
from app.modules.menu.repository import SqlAlchemyMenuRepository

CATEGORY_NAMES = ["Супы", "Горячее", "Гарниры", "Салаты", "Выпечка",
                  "Десерты", "Напитки", "Завтраки", "Пицца", "Роллы"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--categories", type=int, default=10)
    parser.add_argument("--items", type=int, default=20, help="блюд в каждой категории")
    args = parser.parse_args()

    with SessionLocal() as session:
        repo = SqlAlchemyMenuRepository(session)
        created = 0
        for c in range(args.categories):
            name = CATEGORY_NAMES[c] if c < len(CATEGORY_NAMES) else f"Категория {c + 1}"
            category = repo.get_category_by_name(name) or repo.create_category(name)
            for i in range(args.items):
                dish = f"{name}: блюдо {i + 1}"
                if repo.get_item_by_name(dish) is None:
                    repo.create_item(dish, 50.0 + 10 * (i % 20), True, category.id)
                    created += 1
        total = len(repo.list_items())
    print(f"Добавлено блюд: {created}, всего в меню: {total}")


if __name__ == "__main__":
    main()
