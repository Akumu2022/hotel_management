"""distance pricing: per-km mode, road distance, order distance snapshot

Owner request 2026-10-02 (DECISIONS D16).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-02
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_SETTINGS = {
    "rider_fee_mode": "per_km",
    "rider_fee_base": 50,
    "rider_fee_per_km": 20,
    "rider_fee_min": 100,
    "rider_fee_max_km": 10,
    "distance_method": "road",
}


def upgrade() -> None:
    op.add_column("orders", sa.Column("distance_km", sa.Float(), nullable=True))
    conn = op.get_bind()
    for key, value in NEW_SETTINGS.items():
        conn.execute(
            sa.text(
                "INSERT INTO settings (key, value) VALUES (:k, CAST(:v AS jsonb)) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"k": key, "v": json.dumps(value)},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for key in NEW_SETTINGS:
        conn.execute(sa.text("DELETE FROM settings WHERE key = :k"), {"k": key})
    op.drop_column("orders", "distance_km")
