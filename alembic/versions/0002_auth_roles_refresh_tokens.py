"""Аутентификация: password_hash, роли, refresh-токены

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17

Отличия от примера в методичке:
- существующим пользователям пароль неизвестен, поэтому им пишется
  непригодный хеш "!": с ним нельзя войти, пока администратор не задаст пароль.
  Без этого ALTER ... SET NOT NULL на password_hash упал бы на непустой таблице;
- token_version — номер поколения токенов для сброса всех сессий;
- orders.total_cost — списанная сумма, нужна для возврата при отмене заказа;
- изменения колонок идут через batch_alter_table, чтобы миграция работала
  и на PostgreSQL, и на SQLite.
"""
import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# Непригодный хеш: verify_password для него всегда возвращает False.
UNUSABLE_PASSWORD = "!"


def upgrade():
    # Создаём таблицу ролей и сразу заполняем справочник.
    roles = op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(50), unique=True, nullable=False),
    )
    op.bulk_insert(
        roles,
        [{"name": "student"}, {"name": "cook"}, {"name": "courier"}, {"name": "admin"}],
    )

    # Колонки в users пока nullable — заполним ниже.
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("password_hash", sa.String(), nullable=True))
        batch.add_column(sa.Column("role_id", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("token_version", sa.Integer(), nullable=False, server_default="0")
        )
        batch.create_foreign_key("fk_users_role", "roles", ["role_id"], ["id"])

    # Всем существующим пользователям — роль student и непригодный пароль.
    op.execute("UPDATE users SET role_id = (SELECT id FROM roles WHERE name = 'student')")
    op.execute(f"UPDATE users SET password_hash = '{UNUSABLE_PASSWORD}'")

    # Теперь колонки можно сделать обязательными.
    with op.batch_alter_table("users") as batch:
        batch.alter_column("role_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("password_hash", existing_type=sa.String(), nullable=False)

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("is_revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])

    with op.batch_alter_table("orders") as batch:
        batch.add_column(
            sa.Column("total_cost", sa.Float(), nullable=False, server_default="0")
        )
    # Для старых заказов цена на момент заказа не сохранилась, берём текущую.
    op.execute(
        "UPDATE orders SET total_cost = quantity * "
        "(SELECT price FROM menu_items WHERE menu_items.id = orders.item_id) "
        "WHERE item_id IS NOT NULL"
    )


def downgrade():
    with op.batch_alter_table("orders") as batch:
        batch.drop_column("total_cost")
    op.drop_index("ix_refresh_tokens_user_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("fk_users_role", type_="foreignkey")
        batch.drop_column("token_version")
        batch.drop_column("role_id")
        batch.drop_column("password_hash")
    op.drop_table("roles")
