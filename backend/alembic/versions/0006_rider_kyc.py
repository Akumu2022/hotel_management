"""rider KYC: next of kin phone, residence, ID photos, selfie, review status

Owner request 2026-10-02 (DECISIONS D21).

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

T = "rider_profiles"
TZ = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column(T, sa.Column("next_of_kin_phone", sa.String(12), nullable=True))
    op.add_column(T, sa.Column("residence_area", sa.String(200), nullable=True))
    for col in ("id_front_key", "id_back_key", "selfie_key", "photo_key"):
        op.add_column(T, sa.Column(col, sa.String(200), nullable=True))
    op.add_column(T, sa.Column("consent_at", TZ, nullable=True))
    op.add_column(T, sa.Column("kyc_status", sa.String(10), server_default="draft", nullable=False))
    op.add_column(T, sa.Column("kyc_note", sa.String(300), nullable=True))
    op.add_column(T, sa.Column("submitted_at", TZ, nullable=True))
    op.add_column(T, sa.Column("reviewed_by", sa.Uuid(), nullable=True))
    op.add_column(T, sa.Column("reviewed_at", TZ, nullable=True))
    op.create_foreign_key(
        "fk_rider_profiles_reviewed_by_users", T, "users", ["reviewed_by"], ["id"]
    )
    op.create_unique_constraint("uq_rider_profiles_national_id", T, ["national_id"])
    op.create_check_constraint(
        "kyc_status",
        T,
        "kyc_status IN ('draft', 'pending', 'approved', 'rejected', 'suspended')",
    )
    op.create_check_constraint(
        "submitted_complete",
        T,
        "kyc_status = 'draft' OR (id_front_key IS NOT NULL AND id_back_key IS NOT NULL"
        " AND selfie_key IS NOT NULL AND consent_at IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_rider_profiles_submitted_complete"), T, type_="check")
    op.drop_constraint(op.f("ck_rider_profiles_kyc_status"), T, type_="check")
    op.drop_constraint(op.f("uq_rider_profiles_national_id"), T, type_="unique")
    op.drop_constraint(op.f("fk_rider_profiles_reviewed_by_users"), T, type_="foreignkey")
    for col in (
        "reviewed_at",
        "reviewed_by",
        "submitted_at",
        "kyc_note",
        "kyc_status",
        "consent_at",
        "photo_key",
        "selfie_key",
        "id_back_key",
        "id_front_key",
        "residence_area",
        "next_of_kin_phone",
    ):
        op.drop_column(T, col)
