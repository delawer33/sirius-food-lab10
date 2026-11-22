"""Outbox хранит correlation_id и traceparent запроса, породившего событие

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-17
"""
import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("outbox", sa.Column("correlation_id", sa.String(128), nullable=True))
    op.add_column("outbox", sa.Column("trace_context", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("outbox", "trace_context")
    op.drop_column("outbox", "correlation_id")
