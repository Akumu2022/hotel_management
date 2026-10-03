"""payer name on payments and how well it matches the checkout name (D25)

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("payer_name", sa.String(120), nullable=True))
    op.add_column("payments", sa.Column("name_match", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "name_match_range", "payments", "name_match IS NULL OR name_match BETWEEN 0 AND 2"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_payments_name_match_range"), "payments", type_="check")
    op.drop_column("payments", "name_match")
    op.drop_column("payments", "payer_name")
