"""payments module: the rider-fee part of each STK payment

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE payments.stk_requests ADD COLUMN rider_fee integer NOT NULL DEFAULT 0")


def downgrade() -> None:
    op.execute("ALTER TABLE payments.stk_requests DROP COLUMN rider_fee")
