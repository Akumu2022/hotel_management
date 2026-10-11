"""index on orders.created_at: the daily bonus budget sums today's orders across all hotels

The only date index also leads with hotel and status, so that query scanned the whole table and
slowed with every order placed.

Revision ID: 0025
Revises: 0023
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0025"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_orders_created_at", "orders", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_orders_created_at", table_name="orders")
