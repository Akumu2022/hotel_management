"""orders.rider_seen_at: an assigned job rings the rider until seen

Owner request 2026-10-03 (DECISIONS D23).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("rider_seen_at", sa.DateTime(timezone=True), nullable=True))
    # Jobs riders already hold were taken by them: count them as seen.
    op.execute("UPDATE orders SET rider_seen_at = assigned_at WHERE rider_id IS NOT NULL")


def downgrade() -> None:
    op.drop_column("orders", "rider_seen_at")
