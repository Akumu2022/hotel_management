"""billing (M7): statement breakdown, settlement claims, platform M-Pesa number

Owner request 2026-10-03 (DECISIONS D24): hotels pay the platform directly to 0742554713.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-03
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "statements", sa.Column("credits_total", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "statements", sa.Column("opening_balance", sa.Integer(), server_default="0", nullable=False)
    )
    op.create_check_constraint("credits_total_non_negative", "statements", "credits_total >= 0")

    op.add_column(
        "settlements", sa.Column("status", sa.String(10), server_default="pending", nullable=False)
    )
    op.add_column("settlements", sa.Column("claimed_by", sa.Uuid(), nullable=True))
    op.add_column("settlements", sa.Column("note", sa.String(200), nullable=True))
    op.create_foreign_key(
        "fk_settlements_claimed_by_users", "settlements", "users", ["claimed_by"], ["id"]
    )
    op.alter_column(
        "settlements", "confirmed_at", existing_type=sa.DateTime(timezone=True), nullable=True
    )
    op.execute("UPDATE settlements SET status = 'confirmed' WHERE confirmed_at IS NOT NULL")
    op.create_check_constraint(
        "status", "settlements", "status IN ('pending', 'confirmed', 'rejected')"
    )
    op.create_check_constraint(
        "confirmed_at_iff_confirmed",
        "settlements",
        "(status = 'confirmed') = (confirmed_at IS NOT NULL)",
    )

    # A rider can be paid more than once a week (e.g. a top-up after a late compensation).
    op.drop_constraint(op.f("uq_rider_payouts_rider_id"), "rider_payouts", type_="unique")
    op.create_index("ix_rider_payouts_rider_id", "rider_payouts", ["rider_id"])

    op.get_bind().execute(
        sa.text(
            "INSERT INTO settings (key, value) VALUES ('platform_mpesa_number', CAST(:v AS jsonb)) "
            "ON CONFLICT (key) DO NOTHING"
        ),
        {"v": json.dumps("254742554713")},
    )


def downgrade() -> None:
    op.get_bind().execute(sa.text("DELETE FROM settings WHERE key = 'platform_mpesa_number'"))
    op.drop_index("ix_rider_payouts_rider_id", "rider_payouts")
    op.create_unique_constraint(
        op.f("uq_rider_payouts_rider_id"), "rider_payouts", ["rider_id", "period_start"]
    )
    op.drop_constraint(
        op.f("ck_settlements_confirmed_at_iff_confirmed"), "settlements", type_="check"
    )
    op.drop_constraint(op.f("ck_settlements_status"), "settlements", type_="check")
    op.execute("DELETE FROM settlements WHERE status <> 'confirmed'")
    op.alter_column(
        "settlements", "confirmed_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )
    op.drop_constraint(op.f("fk_settlements_claimed_by_users"), "settlements", type_="foreignkey")
    op.drop_column("settlements", "note")
    op.drop_column("settlements", "claimed_by")
    op.drop_column("settlements", "status")
    op.drop_constraint(
        op.f("ck_statements_credits_total_non_negative"), "statements", type_="check"
    )
    op.drop_column("statements", "opening_balance")
    op.drop_column("statements", "credits_total")
