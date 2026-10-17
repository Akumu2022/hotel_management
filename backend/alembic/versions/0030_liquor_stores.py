"""liquor stores: a hotel can be a liquor store, with its licence

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("hotels", sa.Column("kind", sa.String(length=8), server_default="hotel", nullable=False))
    op.add_column("hotels", sa.Column("liquor_licence_no", sa.String(length=60), nullable=True))
    op.add_column("hotels", sa.Column("liquor_licence_expires", sa.Date(), nullable=True))
    op.create_check_constraint("kind", "hotels", "kind IN ('hotel', 'liquor')")


def downgrade() -> None:
    op.drop_constraint("kind", "hotels", type_="check")
    op.drop_column("hotels", "liquor_licence_expires")
    op.drop_column("hotels", "liquor_licence_no")
    op.drop_column("hotels", "kind")
