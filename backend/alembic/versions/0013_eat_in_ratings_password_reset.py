"""eat-in orders, ratings, password reset (D28)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TYPE_RULES = (
    "(type = 'pickup' AND rider_fee_mode = 'none' AND rider_fee = 0)"
    " OR (type = 'delivery' AND rider_fee_mode IN ('included', 'cash')"
    " AND payment_method = 'mpesa' AND lat IS NOT NULL AND lng IS NOT NULL)"
)
_NEW_TYPE_RULES = (
    "(type = 'pickup' AND rider_fee_mode = 'none' AND rider_fee = 0)"
    " OR (type = 'eat_in' AND rider_fee_mode = 'none' AND rider_fee = 0"
    " AND payment_method = 'mpesa' AND arrive_at IS NOT NULL)"
    " OR (type = 'delivery' AND rider_fee_mode IN ('included', 'cash')"
    " AND payment_method = 'mpesa' AND lat IS NOT NULL AND lng IS NOT NULL)"
)


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO settings (key, value) VALUES ('eat_in_fee', '30'::jsonb) "
            "ON CONFLICT (key) DO NOTHING"
        )
    )
    op.add_column(
        "users",
        sa.Column("must_change_password", sa.Boolean(), server_default="false", nullable=False),
    )

    op.add_column(
        "orders", sa.Column("eat_in_fee", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("orders", sa.Column("arrive_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_orders_eat_in_fee_non_negative"), "orders", "eat_in_fee >= 0"
    )
    op.create_check_constraint(
        op.f("ck_orders_eat_in_fee_within_service_fee"), "orders", "eat_in_fee <= service_fee"
    )
    op.drop_constraint(op.f("ck_orders_type"), "orders", type_="check")
    op.create_check_constraint(
        op.f("ck_orders_type"), "orders", "type IN ('delivery', 'pickup', 'eat_in')"
    )
    op.drop_constraint(op.f("ck_orders_type_rules"), "orders", type_="check")
    op.create_check_constraint(op.f("ck_orders_type_rules"), "orders", _NEW_TYPE_RULES)

    op.create_table(
        "ratings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("hotel_id", sa.Uuid(), nullable=False),
        sa.Column("rider_id", sa.Uuid(), nullable=True),
        sa.Column("hotel_stars", sa.SmallInteger(), nullable=False),
        sa.Column("rider_stars", sa.SmallInteger(), nullable=True),
        sa.Column("comment", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "hotel_stars BETWEEN 1 AND 5", name=op.f("ck_ratings_hotel_stars_range")
        ),
        sa.CheckConstraint(
            "rider_stars IS NULL OR rider_stars BETWEEN 1 AND 5",
            name=op.f("ck_ratings_rider_stars_range"),
        ),
        sa.CheckConstraint(
            "(rider_stars IS NULL) = (rider_id IS NULL)", name=op.f("ck_ratings_rider_with_stars")
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"], name=op.f("fk_ratings_order_id_orders")
        ),
        sa.ForeignKeyConstraint(
            ["hotel_id"], ["hotels.id"], name=op.f("fk_ratings_hotel_id_hotels")
        ),
        sa.ForeignKeyConstraint(["rider_id"], ["users.id"], name=op.f("fk_ratings_rider_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ratings")),
        sa.UniqueConstraint("order_id", name=op.f("uq_ratings_order_id")),
    )
    op.create_index(op.f("ix_ratings_hotel_id"), "ratings", ["hotel_id"])
    op.create_index(op.f("ix_ratings_rider_id"), "ratings", ["rider_id"])


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM settings WHERE key = 'eat_in_fee'"))
    op.drop_index(op.f("ix_ratings_rider_id"), table_name="ratings")
    op.drop_index(op.f("ix_ratings_hotel_id"), table_name="ratings")
    op.drop_table("ratings")
    op.drop_constraint(op.f("ck_orders_type_rules"), "orders", type_="check")
    op.create_check_constraint(op.f("ck_orders_type_rules"), "orders", _OLD_TYPE_RULES)
    op.drop_constraint(op.f("ck_orders_type"), "orders", type_="check")
    op.create_check_constraint(op.f("ck_orders_type"), "orders", "type IN ('delivery', 'pickup')")
    op.drop_constraint(op.f("ck_orders_eat_in_fee_within_service_fee"), "orders", type_="check")
    op.drop_constraint(op.f("ck_orders_eat_in_fee_non_negative"), "orders", type_="check")
    op.drop_column("orders", "arrive_at")
    op.drop_column("orders", "eat_in_fee")
    op.drop_column("users", "must_change_password")
