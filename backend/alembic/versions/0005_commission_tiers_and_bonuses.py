"""commission tiers, platform bonuses (stamp card, free delivery), happy-hour discounts

Owner request 2026-10-02 (DECISIONS D19).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-02
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_SETTINGS = {
    "commission_mode": "tiers",
    "commission_tiers": [
        {"up_to": 500, "fee": 20},
        {"up_to": 1000, "fee": 30},
        {"up_to": 2000, "fee": 40},
        {"up_to": 3000, "fee": 50},
        {"up_to": 4000, "fee": 60},
        {"up_to": 5000, "fee": 70},
    ],
    "commission_step": 1000,
    "commission_step_fee": 10,
    "stamp_every": 5,
    "stamp_reward": 100,
    "free_delivery_min_food": 1500,
    "bonus_daily_budget": 2000,
}

OLD_ENTRY_TYPES = (
    "till_received",
    "cash_received",
    "commission",
    "service_fee",
    "commission_reversal",
    "service_fee_reversal",
    "refund",
    "rider_fee_instant",
    "rider_fee_held",
    "rider_fee_owed",
    "rider_fee_cash",
    "rider_compensation",
    "settlement",
    "rider_payout",
)
NEW_ENTRY_TYPES = (*OLD_ENTRY_TYPES, "bonus_credit", "bonus_credit_reversal")


def _in(values: tuple[str, ...]) -> str:
    return "entry_type IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.add_column(
        "orders", sa.Column("platform_bonus", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("orders", sa.Column("bonus_kind", sa.String(16), nullable=True))
    op.create_check_constraint("platform_bonus_non_negative", "orders", "platform_bonus >= 0")
    op.drop_constraint(op.f("ck_orders_till_amount_sum"), "orders", type_="check")
    op.create_check_constraint(
        "till_amount_sum",
        "orders",
        "till_amount = food_net + service_fee + rider_fee_in_till - platform_bonus",
    )
    op.create_check_constraint(
        "bonus_kind_amount",
        "orders",
        "(bonus_kind IS NULL AND platform_bonus = 0)"
        " OR (bonus_kind IN ('stamp', 'free_delivery') AND platform_bonus > 0)",
    )

    op.drop_constraint(op.f("ck_ledger_entries_entry_type"), "ledger_entries", type_="check")
    op.create_check_constraint("entry_type", "ledger_entries", _in(NEW_ENTRY_TYPES))

    op.add_column("discounts", sa.Column("days_mask", sa.Integer(), nullable=True))
    op.add_column("discounts", sa.Column("daily_from", sa.Integer(), nullable=True))
    op.add_column("discounts", sa.Column("daily_to", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "days_mask_range", "discounts", "days_mask IS NULL OR days_mask BETWEEN 1 AND 127"
    )
    op.create_check_constraint(
        "daily_window",
        "discounts",
        "(daily_from IS NULL AND daily_to IS NULL)"
        " OR (daily_from BETWEEN 0 AND 1439 AND daily_to BETWEEN 1 AND 1440"
        " AND daily_to > daily_from)",
    )

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
    op.drop_constraint(op.f("ck_discounts_daily_window"), "discounts", type_="check")
    op.drop_constraint(op.f("ck_discounts_days_mask_range"), "discounts", type_="check")
    op.drop_column("discounts", "daily_to")
    op.drop_column("discounts", "daily_from")
    op.drop_column("discounts", "days_mask")
    op.drop_constraint(op.f("ck_ledger_entries_entry_type"), "ledger_entries", type_="check")
    op.create_check_constraint("entry_type", "ledger_entries", _in(OLD_ENTRY_TYPES))
    op.drop_constraint(op.f("ck_orders_bonus_kind_amount"), "orders", type_="check")
    op.drop_constraint(op.f("ck_orders_till_amount_sum"), "orders", type_="check")
    op.create_check_constraint(
        "till_amount_sum", "orders", "till_amount = food_net + service_fee + rider_fee_in_till"
    )
    op.drop_constraint(op.f("ck_orders_platform_bonus_non_negative"), "orders", type_="check")
    op.drop_column("orders", "bonus_kind")
    op.drop_column("orders", "platform_bonus")
