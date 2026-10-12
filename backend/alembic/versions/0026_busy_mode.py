"""hotel busy mode: extra minutes added to every quoted prep time while orders keep coming

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "hotels", sa.Column("busy_extra_minutes", sa.Integer(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("hotels", "busy_extra_minutes")
