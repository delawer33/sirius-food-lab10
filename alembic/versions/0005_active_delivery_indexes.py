"""Уникальность активной доставки

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-21

Правила «у курьера одна активная доставка» и «заказ везёт один курьер»
проверял код монолита. Теперь доставки в микросервисе, и два одновременных
AssignCourier прошли бы оба. Частичные уникальные индексы держат правило в БД.
"""
import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

ACTIVE = sa.text("status = 'in_progress'")


def upgrade():
    op.create_index("uq_deliveries_active_courier", "deliveries", ["courier_id"], unique=True,
                    postgresql_where=ACTIVE, sqlite_where=ACTIVE)
    op.create_index("uq_deliveries_active_order", "deliveries", ["order_id"], unique=True,
                    postgresql_where=ACTIVE, sqlite_where=ACTIVE)


def downgrade():
    op.drop_index("uq_deliveries_active_order", table_name="deliveries")
    op.drop_index("uq_deliveries_active_courier", table_name="deliveries")
