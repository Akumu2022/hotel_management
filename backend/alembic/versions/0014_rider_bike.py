"""rider bike details: number plate, description, optional logbook photo

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable so riders who joined before this existed keep working; new applications must fill them.
    op.add_column("rider_profiles", sa.Column("bike_plate", sa.String(length=12), nullable=True))
    op.add_column("rider_profiles", sa.Column("bike_description", sa.String(length=200), nullable=True))
    op.add_column("rider_profiles", sa.Column("logbook_key", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("rider_profiles", "logbook_key")
    op.drop_column("rider_profiles", "bike_description")
    op.drop_column("rider_profiles", "bike_plate")
