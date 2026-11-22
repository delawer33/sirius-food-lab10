"""Фоновые задачи: время заказа, журнал задач, статистика

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-21

Старым заказам время создания неизвестно, им ставится момент миграции.
"""
import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders") as batch:
        batch.add_column(
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now())
        )
        batch.create_index("ix_orders_created_at", ["created_at"])

    op.create_table(
        "task_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("task_name", sa.String(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("detail", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_task_logs_order_id", "task_logs", ["order_id"])
    op.create_index("ix_task_logs_created_at", "task_logs", ["created_at"])

    op.create_table(
        "order_stats",
        sa.Column("day", sa.Date(), primary_key=True),
        sa.Column("orders_count", sa.Integer(), nullable=False),
        sa.Column("revenue", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("order_stats")
    op.drop_index("ix_task_logs_created_at", "task_logs")
    op.drop_index("ix_task_logs_order_id", "task_logs")
    op.drop_table("task_logs")
    with op.batch_alter_table("orders") as batch:
        batch.drop_index("ix_orders_created_at")
        batch.drop_column("created_at")
