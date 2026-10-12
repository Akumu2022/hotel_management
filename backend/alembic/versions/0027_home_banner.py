"""home banner settings

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KEYS = ("banner_greeting", "banner_title", "banner_note", "banner_emoji", "banner_image_key")


def upgrade() -> None:
    for key in KEYS:
        op.execute(
            sa.text(
                f"INSERT INTO settings (key, value) VALUES ('{key}', '\"\"'::jsonb) "
                "ON CONFLICT (key) DO NOTHING"
            )
        )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM settings WHERE key IN (" + ",".join(f"'{k}'" for k in KEYS) + ")"))
