"""nearby hotels radius (30 km) and delivery range raised from 10 km to 30 km

Owner request 2026-10-11: customers see hotels near them; delivery reaches 30 km.
Only values still at the old defaults are changed; anything the owner edited is kept.

Revision ID: 0023
Revises: 0015
Create Date: 2026-10-11
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_BANDS = [{"max_km": 2, "fee": 100}, {"max_km": 5, "fee": 150}, {"max_km": 10, "fee": 200}]
NEW_BANDS = OLD_BANDS + [{"max_km": 30, "fee": 350}]


def _swap(key: str, old, new) -> None:
    op.get_bind().execute(
        sa.text("UPDATE settings SET value = CAST(:n AS jsonb) WHERE key = :k AND value = CAST(:o AS jsonb)"),
        {"k": key, "o": json.dumps(old), "n": json.dumps(new)},
    )


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "INSERT INTO settings (key, value) VALUES ('nearby_radius_km', CAST('30' AS jsonb)) "
            "ON CONFLICT (key) DO NOTHING"
        )
    )
    _swap("rider_fee_max_km", 10, 30)
    _swap("rider_fee_bands", OLD_BANDS, NEW_BANDS)


def downgrade() -> None:
    _swap("rider_fee_max_km", 30, 10)
    _swap("rider_fee_bands", NEW_BANDS, OLD_BANDS)
    op.get_bind().execute(sa.text("DELETE FROM settings WHERE key = 'nearby_radius_km'"))
