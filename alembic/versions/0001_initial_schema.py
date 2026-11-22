"""Начальная схема: таблицы MVP и лабораторной работы № 2

Revision ID: 0001
Revises:
Create Date: 2026-10-17

БД, созданные в лабораторной № 2 через Base.metadata.create_all, уже содержат
эти таблицы. Для них вместо upgrade выполняется `alembic stamp 0001`.
"""
import sqlalchemy as sa

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("balance", sa.Float(), nullable=True),
        sa.Column("is_blocked", sa.Boolean(), nullable=True),
    )
    op.create_index("ix_users_id", "users", ["id"])
    op.create_table(
        "menu_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=True),
    )
    op.create_index("ix_menu_items_id", "menu_items", ["id"])
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("menu_items.id"), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
    )
    op.create_index("ix_orders_id", "orders", ["id"])
    op.create_table(
        "deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("courier_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
    )
    op.create_index("ix_deliveries_id", "deliveries", ["id"])


def downgrade():
    op.drop_table("deliveries")
    op.drop_table("orders")
    op.drop_table("menu_items")
    op.drop_table("users")
