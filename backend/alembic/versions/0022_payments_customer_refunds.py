"""payments module: customer refunds

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE payments.wallet_entries DROP CONSTRAINT ck_wallet_entries_party_type")
    op.execute(
        "ALTER TABLE payments.wallet_entries ADD CONSTRAINT ck_wallet_entries_party_type "
        "CHECK (party_type IN ('rider','hotel','platform','customer'))"
    )
    op.execute(
        """
        CREATE TABLE payments.customer_refunds (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            order_ref varchar(40) NOT NULL,
            phone varchar(16) NOT NULL,
            amount integer NOT NULL
                CONSTRAINT ck_customer_refunds_amount_positive CHECK (amount > 0),
            reason varchar(300) NOT NULL,
            status varchar(14) NOT NULL DEFAULT 'queued'
                CONSTRAINT ck_customer_refunds_status CHECK (status IN
                ('queued','submitted','succeeded','failed','unknown','manual_review')),
            attempt integer NOT NULL DEFAULT 1,
            retry_of uuid,
            conversation_id varchar(80) UNIQUE,
            transaction_id varchar(30) UNIQUE,
            result_code integer,
            result_desc varchar(300),
            submitted_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_refund_order ON payments.customer_refunds (order_ref) "
        "WHERE status <> 'failed'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE payments.customer_refunds")
    op.execute("ALTER TABLE payments.wallet_entries DROP CONSTRAINT ck_wallet_entries_party_type")
    op.execute(
        "ALTER TABLE payments.wallet_entries ADD CONSTRAINT ck_wallet_entries_party_type "
        "CHECK (party_type IN ('rider','hotel','platform'))"
    )
