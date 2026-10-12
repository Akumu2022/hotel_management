"""home banner colours

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEYS = ("banner_bg_color", "banner_text_color")


def upgrade() -> None:
    for key in KEYS:
        op.execute(
            sa.text(
                f"INSERT INTO settings (key, value) VALUES ('{key}', '\"\"'::jsonb) "
                "ON CONFLICT (key) DO NOTHING"
            )
        )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM settings WHERE key IN ('banner_bg_color', 'banner_text_color')"))
