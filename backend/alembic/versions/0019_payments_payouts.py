"""payments module: B2C payouts and job markers

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE payments.payouts (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            rider_id uuid NOT NULL,
            kind varchar(16) NOT NULL
                CONSTRAINT ck_payouts_kind CHECK (kind IN ('auto','withdraw','withdraw_extra')),
            payout_date date NOT NULL,
            phone varchar(16) NOT NULL,
            amount integer NOT NULL,
            charge integer NOT NULL DEFAULT 0,
            status varchar(14) NOT NULL DEFAULT 'queued'
                CONSTRAINT ck_payouts_status CHECK (status IN
                ('queued','submitted','succeeded','failed','unknown','manual_review')),
            idem_key varchar(80) UNIQUE,
            retry_of uuid,
            conversation_id varchar(80) UNIQUE,
            transaction_id varchar(30) UNIQUE,
            result_code integer,
            reason varchar(300),
            submitted_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_payouts_amounts CHECK (amount > 0 AND charge >= 0)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_payout_rider_day ON payments.payouts (rider_id, payout_date) "
        "WHERE kind IN ('auto','withdraw') AND status <> 'failed'"
    )
    op.execute("CREATE INDEX ix_payout_status ON payments.payouts (status)")
    op.execute(
        """
        CREATE TABLE payments.job_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            job varchar(40) NOT NULL,
            run_key varchar(40) NOT NULL,
            detail jsonb,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (job, run_key)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE payments.job_runs")
    op.execute("DROP TABLE payments.payouts")
