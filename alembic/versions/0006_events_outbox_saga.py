"""Event-driven: outbox, обработанные события, очередь кухни, возвраты, таблицы сервиса доставки

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-06

courier_shifts, delivery_requests и delivery_processed_events принадлежат
сервису доставки (delivery_service/storage.py). Пока база общая, их создаёт
эта миграция, как раньше deliveries.
"""
import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

UNPUBLISHED = sa.text("published_at IS NULL")


def upgrade():
    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False, unique=True),
        sa.Column("routing_key", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(), nullable=True),
    )
    op.create_index("ix_outbox_unpublished", "outbox", ["id"],
                    postgresql_where=UNPUBLISHED, sqlite_where=UNPUBLISHED)
    op.create_table(
        "processed_events",
        sa.Column("consumer", sa.String(), primary_key=True),
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("processed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "kitchen_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "refunds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False, unique=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    # Таблицы сервиса доставки.
    op.create_table(
        "courier_shifts",
        sa.Column("courier_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("on_shift", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "delivery_requests",
        sa.Column("order_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("free_couriers", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "delivery_processed_events",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("processed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )


def downgrade():
    for table in ("delivery_processed_events", "delivery_requests", "courier_shifts",
                  "refunds", "kitchen_orders", "processed_events"):
        op.drop_table(table)
    op.drop_index("ix_outbox_unpublished", table_name="outbox")
    op.drop_table("outbox")
