"""hotel location and rider fee bands

Owner decision 2026-10-02 (DECISIONS D14): the rider fee depends on the distance from the hotel
to the customer's pin, in admin-set bands. Hotels get a map location to measure from.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen copy of the default bands at the time of this migration.
DEFAULT_BANDS = [
    {"max_km": 2.0, "fee": 100},
    {"max_km": 5.0, "fee": 150},
    {"max_km": 10.0, "fee": 200},
]


def upgrade() -> None:
    op.add_column("hotels", sa.Column("lat", sa.Float(), nullable=True))
    op.add_column("hotels", sa.Column("lng", sa.Float(), nullable=True))
    op.create_check_constraint(
        op.f("ck_hotels_location_both_or_none"), "hotels", "(lat IS NULL) = (lng IS NULL)"
    )

    # rider_fee (flat) -> rider_fee_bands. If an admin had changed the flat fee, keep it as the
    # nearest band so nothing jumps for existing setups.
    conn = op.get_bind()
    flat = conn.execute(sa.text("SELECT value FROM settings WHERE key = 'rider_fee'")).scalar()
    bands = [dict(b) for b in DEFAULT_BANDS]
    if isinstance(flat, int) and flat != bands[0]["fee"]:
        bands[0]["fee"] = flat
        for b in bands[1:]:
            b["fee"] = max(b["fee"], flat)
    conn.execute(
        sa.text(
            "INSERT INTO settings (key, value) VALUES ('rider_fee_bands', CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"v": json.dumps(bands)},
    )
    conn.execute(sa.text("DELETE FROM settings WHERE key = 'rider_fee'"))


def downgrade() -> None:
    conn = op.get_bind()
    bands = conn.execute(
        sa.text("SELECT value FROM settings WHERE key = 'rider_fee_bands'")
    ).scalar()
    flat = bands[0]["fee"] if bands else 100
    conn.execute(
        sa.text(
            "INSERT INTO settings (key, value) VALUES ('rider_fee', CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"v": json.dumps(flat)},
    )
    conn.execute(sa.text("DELETE FROM settings WHERE key = 'rider_fee_bands'"))
    op.drop_constraint(op.f("ck_hotels_location_both_or_none"), "hotels", type_="check")
    op.drop_column("hotels", "lng")
    op.drop_column("hotels", "lat")
