"""payments module: own schema, wallet ledger, outbox (additive; no pilot table touched)

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA payments")
    op.execute(
        """
        CREATE TABLE payments.wallet_entries (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            idem_key varchar(120) NOT NULL UNIQUE,
            group_id uuid NOT NULL,
            party_type varchar(10) NOT NULL
                CONSTRAINT ck_wallet_entries_party_type CHECK (party_type IN ('rider','hotel','platform')),
            party_id uuid,
            bucket varchar(10) NOT NULL
                CONSTRAINT ck_wallet_entries_bucket CHECK (bucket IN ('pending','available','reserved','paid')),
            amount bigint NOT NULL
                CONSTRAINT ck_wallet_entries_amount_nonzero CHECK (amount <> 0),
            kind varchar(30) NOT NULL,
            order_ref varchar(40),
            shadow boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_wallet_party ON payments.wallet_entries "
        "(party_type, party_id, bucket, shadow)"
    )
    op.execute("CREATE INDEX ix_wallet_order ON payments.wallet_entries (order_ref)")
    op.execute(
        """
        CREATE TABLE payments.outbox (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            topic varchar(40) NOT NULL,
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            processed_at timestamptz,
            attempts integer NOT NULL DEFAULT 0
        )
        """
    )
    # Append-only ledger: corrections are new entries.
    op.execute(
        """
        CREATE FUNCTION payments.forbid_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER wallet_entries_append_only BEFORE UPDATE OR DELETE ON "
        "payments.wallet_entries FOR EACH ROW EXECUTE FUNCTION payments.forbid_change()"
    )
    op.execute(
        "CREATE TRIGGER wallet_entries_no_truncate BEFORE TRUNCATE ON "
        "payments.wallet_entries FOR EACH STATEMENT EXECUTE FUNCTION payments.forbid_change()"
    )


def downgrade() -> None:
    op.execute("DROP SCHEMA payments CASCADE")
