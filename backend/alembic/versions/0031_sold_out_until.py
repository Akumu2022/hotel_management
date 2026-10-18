"""products: sold out until (back tomorrow)

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-18
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0031"
down_revision: str | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("sold_out_until", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("products", "sold_out_until")
