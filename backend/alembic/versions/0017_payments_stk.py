"""payments module: STK requests and raw callbacks

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE payments.stk_requests (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            order_ref varchar(40) NOT NULL,
            phone varchar(16) NOT NULL,
            amount integer NOT NULL
                CONSTRAINT ck_stk_requests_amount_positive CHECK (amount > 0),
            status varchar(10) NOT NULL DEFAULT 'created'
                CONSTRAINT ck_stk_requests_status CHECK (status IN
                ('created','sent','failed','success','cancelled','review')),
            checkout_request_id varchar(80) UNIQUE,
            merchant_request_id varchar(80),
            receipt varchar(20),
            result_code integer,
            result_desc varchar(300),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_stk_order ON payments.stk_requests (order_ref)")
    op.execute(
        "CREATE UNIQUE INDEX uq_stk_receipt ON payments.stk_requests (receipt) "
        "WHERE receipt IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE payments.raw_callbacks (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            kind varchar(20) NOT NULL,
            external_id varchar(120) NOT NULL,
            body jsonb NOT NULL,
            processed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (kind, external_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE payments.raw_callbacks")
    op.execute("DROP TABLE payments.stk_requests")
