"""
Окружение Alembic. Строка подключения и метаданные берутся из приложения,
поэтому миграции работают с той же БД, что и uvicorn.
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

import app.models  # noqa: F401 — регистрирует модели в Base.metadata
from app.core.config import settings
from app.database import Base
from delivery_service.storage import OWN_TABLES as DELIVERY_SERVICE_TABLES

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    """Таблицы сервиса доставки создаёт эта же миграция, но в моделях монолита их нет."""
    table = obj.table.name if type_ in ("column", "index", "unique_constraint") else name
    return table not in DELIVERY_SERVICE_TABLES


def run_migrations_offline() -> None:
    """Генерирует SQL-скрипт без подключения к БД (alembic upgrade --sql)."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # render_as_batch: SQLite не умеет ALTER COLUMN, Alembic пересоздаёт таблицу.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
