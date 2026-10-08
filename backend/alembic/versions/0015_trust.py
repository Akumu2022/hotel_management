"""trust: the Till's registered name and the Chakula team's hotel check

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hotels", sa.Column("till_name", sa.String(length=80), nullable=True))
    op.add_column("hotels", sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("hotels", "verified_at")
    op.drop_column("hotels", "till_name")
