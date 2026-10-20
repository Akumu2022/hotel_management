"""extras: a hotel's shared extra groups (required / pick-one / up-to-N) attached to many dishes

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0033"
down_revision: str | None = "0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "extra_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("hotel_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("hotels.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("min_picks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_picks", sa.Integer()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("hotel_id", "name", name="uq_extra_groups_hotel_id"),
        sa.CheckConstraint("min_picks >= 0", name="ck_extra_groups_min_picks_non_negative"),
        sa.CheckConstraint("max_picks IS NULL OR max_picks >= 1", name="ck_extra_groups_max_picks_positive"),
        sa.CheckConstraint("max_picks IS NULL OR max_picks >= min_picks", name="ck_extra_groups_max_at_least_min"),
    )
    op.create_index("ix_extra_groups_hotel_id", "extra_groups", ["hotel_id"])
    op.create_table(
        "extra_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("extra_groups.id"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("price_delta", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_sold_out", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("price_delta >= 0", name="ck_extra_items_price_delta_non_negative"),
    )
    op.create_index("ix_extra_items_group_id", "extra_items", ["group_id"])
    op.create_table(
        "product_extra_groups",
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id"), primary_key=True),
        sa.Column("group_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("extra_groups.id"), primary_key=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_table("product_extra_groups")
    op.drop_table("extra_items")
    op.drop_table("extra_groups")
