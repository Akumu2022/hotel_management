"""who paid on M-Pesa (name and number), typed with the code

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("mpesa_name", sa.String(length=120), nullable=True))
    op.add_column("orders", sa.Column("mpesa_phone", sa.String(length=12), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "mpesa_phone")
    op.drop_column("orders", "mpesa_name")
