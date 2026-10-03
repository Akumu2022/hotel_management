"""support whatsapp setting

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO settings (key, value) VALUES ('support_whatsapp', '\"\"'::jsonb) "
            "ON CONFLICT (key) DO NOTHING"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM settings WHERE key = 'support_whatsapp'"))
