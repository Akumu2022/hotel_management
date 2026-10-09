"""payments module: hotel and platform shares, hotel settlements

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE payments.stk_requests ADD COLUMN hotel_id uuid")
    op.execute(
        "ALTER TABLE payments.stk_requests ADD COLUMN hotel_share integer NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE payments.stk_requests ADD COLUMN platform_fee integer NOT NULL DEFAULT 0"
    )
    # The platform's own earnings get a bucket, so they never count as money owed to others.
    op.execute("ALTER TABLE payments.wallet_entries DROP CONSTRAINT ck_wallet_entries_bucket")
    op.execute(
        "ALTER TABLE payments.wallet_entries ADD CONSTRAINT ck_wallet_entries_bucket "
        "CHECK (bucket IN ('pending','available','reserved','paid','earned'))"
    )
    op.execute(
        """
        CREATE TABLE payments.hotel_settlements (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            hotel_id uuid NOT NULL,
            statement_date date NOT NULL,
            channel varchar(6) NOT NULL,
            destination varchar(20) NOT NULL,
            amount integer NOT NULL CONSTRAINT ck_hotel_settlements_amount_positive CHECK (amount > 0),
            status varchar(14) NOT NULL DEFAULT 'queued'
                CONSTRAINT ck_hotel_settlements_status CHECK (status IN
                ('queued','submitted','succeeded','failed','unknown','manual_review')),
            detail jsonb,
            conversation_id varchar(80) UNIQUE,
            transaction_id varchar(30) UNIQUE,
            result_code integer,
            reason varchar(300),
            submitted_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_settlement_hotel_day ON payments.hotel_settlements "
        "(hotel_id, statement_date) WHERE status <> 'failed'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE payments.hotel_settlements")
    op.execute("ALTER TABLE payments.wallet_entries DROP CONSTRAINT ck_wallet_entries_bucket")
    op.execute(
        "ALTER TABLE payments.wallet_entries ADD CONSTRAINT ck_wallet_entries_bucket "
        "CHECK (bucket IN ('pending','available','reserved','paid'))"
    )
    op.execute("ALTER TABLE payments.stk_requests DROP COLUMN platform_fee")
    op.execute("ALTER TABLE payments.stk_requests DROP COLUMN hotel_share")
    op.execute("ALTER TABLE payments.stk_requests DROP COLUMN hotel_id")
