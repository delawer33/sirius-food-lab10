"""
Миграции Alembic: применяются к БД из лабораторной № 2 с данными
и откатываются обратно.
"""
import sqlite3

import pytest
from alembic import command
from alembic.config import Config

from app.core import config as app_config


@pytest.fixture
def alembic_cfg(tmp_path, monkeypatch):
    db_file = tmp_path / "migrate.db"
    monkeypatch.setattr(app_config.settings, "DATABASE_URL", f"sqlite:///{db_file}")
    cfg = Config("alembic.ini")
    return cfg, db_file


def test_upgrade_existing_data_and_downgrade(alembic_cfg):
    cfg, db_file = alembic_cfg
    command.upgrade(cfg, "0001")
    with sqlite3.connect(db_file) as conn:
        conn.execute("INSERT INTO users (email, balance, is_blocked) VALUES ('old@sirius.ru', 10, 0)")
        conn.execute("INSERT INTO menu_items (name, price, is_available) VALUES ('Борщ', 200, 1)")
        conn.execute("INSERT INTO orders (user_id, item_id, quantity, status) VALUES (1, 1, 2, 'processing')")

    command.upgrade(cfg, "head")

    with sqlite3.connect(db_file) as conn:
        roles = [name for (name,) in conn.execute("SELECT name FROM roles ORDER BY id")]
        user = conn.execute(
            "SELECT r.name, u.password_hash, u.token_version FROM users u JOIN roles r ON r.id = u.role_id"
        ).fetchone()
        total = conn.execute("SELECT total_cost FROM orders").fetchone()[0]
        category = conn.execute("SELECT category_id FROM menu_items").fetchone()[0]
        created_at = conn.execute("SELECT created_at FROM orders").fetchone()[0]
    assert roles == ["student", "cook", "courier", "admin"]
    # Старому пользователю назначен student и непригодный пароль.
    assert user == ("student", "!", 0)
    assert total == 400
    # Блюдо из лабы 2 осталось без категории.
    assert category is None
    # Старому заказу проставлено время миграции.
    assert created_at is not None

    command.downgrade(cfg, "base")
    with sqlite3.connect(db_file) as conn:
        tables = {name for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"alembic_version"}
