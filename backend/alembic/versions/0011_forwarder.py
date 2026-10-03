"""SMS forwarder (M8): pairing codes and phone health reports

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("forwarder_devices", sa.Column("app_version", sa.String(20), nullable=True))
    op.add_column(
        "forwarder_devices", sa.Column("last_sms_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "forwarder_devices",
        sa.Column(
            "last_report",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    op.create_table(
        "forwarder_pairings",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("hotel_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["hotel_id"], ["hotels.id"], name=op.f("fk_forwarder_pairings_hotel_id_hotels")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"],
            ["forwarder_devices.id"],
            name=op.f("fk_forwarder_pairings_device_id_forwarder_devices"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_forwarder_pairings_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forwarder_pairings")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_forwarder_pairings_code_hash")),
    )
    op.create_index(
        op.f("ix_forwarder_pairings_hotel_id"), "forwarder_pairings", ["hotel_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_forwarder_pairings_hotel_id"), table_name="forwarder_pairings")
    op.drop_table("forwarder_pairings")
    op.drop_column("forwarder_devices", "last_report")
    op.drop_column("forwarder_devices", "last_sms_at")
    op.drop_column("forwarder_devices", "app_version")
