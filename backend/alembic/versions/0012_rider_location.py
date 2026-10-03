"""rider live location (D27): latest fix on the profile, pings during jobs

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("rider_profiles", sa.Column("last_lat", sa.Float(), nullable=True))
    op.add_column("rider_profiles", sa.Column("last_lng", sa.Float(), nullable=True))
    op.add_column("rider_profiles", sa.Column("last_accuracy_m", sa.SmallInteger(), nullable=True))
    op.add_column(
        "rider_profiles",
        sa.Column("last_location_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "rider_pings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("rider_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("accuracy_m", sa.SmallInteger(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["rider_id"], ["users.id"], name=op.f("fk_rider_pings_rider_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_rider_pings_order_id_orders")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rider_pings")),
    )
    op.create_index("ix_rider_pings_rider_at", "rider_pings", ["rider_id", "at"])
    op.create_index(op.f("ix_rider_pings_order_id"), "rider_pings", ["order_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_rider_pings_order_id"), table_name="rider_pings")
    op.drop_index("ix_rider_pings_rider_at", table_name="rider_pings")
    op.drop_table("rider_pings")
    op.drop_column("rider_profiles", "last_location_at")
    op.drop_column("rider_profiles", "last_accuracy_m")
    op.drop_column("rider_profiles", "last_lng")
    op.drop_column("rider_profiles", "last_lat")
