"""delivery: assignment, rider fee confirmations, delivery code attempts, fee disputes, strikes

Owner request 2026-10-02 (DECISIONS D21).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TZ = sa.DateTime(timezone=True)
OLD_ENTRY_TYPES = (
    "till_received",
    "cash_received",
    "commission",
    "service_fee",
    "commission_reversal",
    "service_fee_reversal",
    "bonus_credit",
    "bonus_credit_reversal",
    "refund",
    "rider_fee_instant",
    "rider_fee_held",
    "rider_fee_owed",
    "rider_fee_cash",
    "rider_compensation",
    "settlement",
    "rider_payout",
)
NEW_ENTRY_TYPES = (*OLD_ENTRY_TYPES, "failed_delivery_credit")


def _in(values: tuple[str, ...]) -> str:
    return "entry_type IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    for col in (
        "assigned_at",
        "fee_hotel_confirmed_at",
        "fee_rider_confirmed_at",
        "fee_not_paid_at",
    ):
        op.add_column("orders", sa.Column(col, TZ, nullable=True))
    op.add_column(
        "orders",
        sa.Column("delivery_code_attempts", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column("orders", sa.Column("customer_fee_answer", sa.String(3), nullable=True))
    op.create_check_constraint(
        "customer_fee_answer",
        "orders",
        "customer_fee_answer IS NULL OR customer_fee_answer IN ('yes', 'no')",
    )
    op.create_table(
        "rider_strikes",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("rider_id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", TZ, server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], name="fk_rider_strikes_rider_id_users"),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name="fk_rider_strikes_order_id_orders"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_rider_strikes_created_by_users"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_rider_strikes"),
        sa.UniqueConstraint("order_id", name="uq_rider_strikes_order_id"),
    )
    op.create_index("ix_rider_strikes_rider_id", "rider_strikes", ["rider_id"])
    op.drop_constraint(op.f("ck_ledger_entries_entry_type"), "ledger_entries", type_="check")
    op.create_check_constraint("entry_type", "ledger_entries", _in(NEW_ENTRY_TYPES))


def downgrade() -> None:
    op.drop_constraint(op.f("ck_ledger_entries_entry_type"), "ledger_entries", type_="check")
    op.create_check_constraint("entry_type", "ledger_entries", _in(OLD_ENTRY_TYPES))
    op.drop_index("ix_rider_strikes_rider_id", table_name="rider_strikes")
    op.drop_table("rider_strikes")
    op.drop_constraint(op.f("ck_orders_customer_fee_answer"), "orders", type_="check")
    for col in (
        "customer_fee_answer",
        "delivery_code_attempts",
        "fee_not_paid_at",
        "fee_rider_confirmed_at",
        "fee_hotel_confirmed_at",
        "assigned_at",
    ):
        op.drop_column("orders", col)
