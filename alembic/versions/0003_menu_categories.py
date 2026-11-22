"""Категории меню

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21

Существующие блюда остаются без категории (category_id = NULL).
"""
import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), unique=True, nullable=False),
    )
    with op.batch_alter_table("menu_items") as batch:
        batch.add_column(sa.Column("category_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_menu_items_category", "categories", ["category_id"], ["id"])
        batch.create_index("ix_menu_items_category_id", ["category_id"])


def downgrade():
    with op.batch_alter_table("menu_items") as batch:
        batch.drop_index("ix_menu_items_category_id")
        batch.drop_constraint("fk_menu_items_category", type_="foreignkey")
        batch.drop_column("category_id")
    op.drop_table("categories")
