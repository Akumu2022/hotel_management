"""payments module: which hotels take STK payments at checkout

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE payments.hotel_flags (
            hotel_id uuid PRIMARY KEY,
            stk_enabled boolean NOT NULL DEFAULT false,
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE payments.hotel_flags")
