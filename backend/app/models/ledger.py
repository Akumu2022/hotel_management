import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, non_negative, one_of, uuid_pk
from app.models.enums import LEDGER_KINDS, PARTIES, STATEMENT_STATUSES

# Entry type -> (kind, from_party, to_party).
#  obligation: from_party owes to_party the amount (reversals are obligations the other way).
#  payment:    money actually moved from from_party to to_party.
ENTRY_TYPES: dict[str, tuple[str, str, str]] = {
    "till_received": ("payment", "customer", "hotel"),
    "cash_received": ("payment", "customer", "hotel"),
    "commission": ("obligation", "hotel", "platform"),
    "service_fee": ("obligation", "hotel", "platform"),
    "commission_reversal": ("obligation", "platform", "hotel"),
    "service_fee_reversal": ("obligation", "platform", "hotel"),
    "bonus_credit": ("obligation", "platform", "hotel"),  # platform-funded bonus (D19)
    "bonus_credit_reversal": ("obligation", "hotel", "platform"),
    # Rider-fault failed delivery (D7): the hotel refunded the customer; the platform makes
    # the hotel whole on its statement.
    "failed_delivery_credit": ("obligation", "platform", "hotel"),
    "refund": ("payment", "hotel", "customer"),
    "rider_fee_instant": ("payment", "hotel", "rider"),  # option A instant, both confirmed
    "rider_fee_held": ("obligation", "hotel", "platform"),  # option A weekly
    "rider_fee_owed": ("obligation", "platform", "rider"),  # option A weekly
    "rider_fee_cash": ("payment", "customer", "rider"),  # option B
    "rider_compensation": ("obligation", "platform", "rider"),  # option B unpaid (D8)
    "settlement": ("payment", "hotel", "platform"),
    "rider_payout": ("payment", "platform", "rider"),
}


class LedgerEntry(Base):
    """Append-only money record. A DB trigger rejects UPDATE and DELETE."""

    __tablename__ = "ledger_entries"
    __table_args__ = (
        one_of("entry_type", tuple(ENTRY_TYPES)),
        one_of("kind", LEDGER_KINDS),
        one_of("from_party", PARTIES),
        one_of("to_party", PARTIES),
        CheckConstraint("amount > 0", name="amount_positive"),
        # Idempotency guards (spec section 13, D3: refund entries are keyed per refund).
        Index(
            "uq_ledger_order_entry",
            "order_id",
            "entry_type",
            unique=True,
            postgresql_where=text("order_id IS NOT NULL AND refund_id IS NULL"),
        ),
        Index(
            "uq_ledger_refund_entry",
            "refund_id",
            "entry_type",
            unique=True,
            postgresql_where=text("refund_id IS NOT NULL"),
        ),
        Index(
            "uq_ledger_statement_entry",
            "statement_id",
            "entry_type",
            unique=True,
            postgresql_where=text("statement_id IS NOT NULL"),
        ),
        Index(
            "uq_ledger_settlement_entry",
            "settlement_id",
            "entry_type",
            unique=True,
            postgresql_where=text("settlement_id IS NOT NULL"),
        ),
        Index(
            "uq_ledger_payout_entry",
            "payout_id",
            "entry_type",
            unique=True,
            postgresql_where=text("payout_id IS NOT NULL"),
        ),
        Index("ix_ledger_from", "from_party", "from_id"),
        Index("ix_ledger_to", "to_party", "to_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    entry_type: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(12))
    from_party: Mapped[str] = mapped_column(String(10))
    from_id: Mapped[uuid.UUID | None] = mapped_column()
    to_party: Mapped[str] = mapped_column(String(10))
    to_id: Mapped[uuid.UUID | None] = mapped_column()
    amount: Mapped[int] = mapped_column(Integer)
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"), index=True)
    refund_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("refunds.id"))
    statement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("statements.id"))
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("settlements.id"))
    payout_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rider_payouts.id"))
    reference: Mapped[str | None] = mapped_column(String(64))  # M-Pesa code etc.
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()


class Statement(Base):
    __tablename__ = "statements"
    __table_args__ = (
        UniqueConstraint("hotel_id", "week_start"),
        one_of("status", STATEMENT_STATUSES),
        *non_negative(
            "commission_total",
            "service_fee_total",
            "rider_fees_held",
            "credits_total",
            "amount_due",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id"))
    week_start: Mapped[date] = mapped_column(Date)
    commission_total: Mapped[int] = mapped_column(Integer)
    service_fee_total: Mapped[int] = mapped_column(Integer)
    rider_fees_held: Mapped[int] = mapped_column(Integer)
    # D24: what the platform owed the hotel that week (bonuses, failed-delivery credits), and the
    # balance carried in from before (negative = the hotel had paid ahead).
    credits_total: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    opening_balance: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    amount_due: Mapped[int] = mapped_column(Integer)
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(8), default="open", server_default="open")
    created_at: Mapped[datetime] = created_at()


class Settlement(Base):
    """A hotel's payment to the platform (D24): sent by M-Pesa to the platform's number, claimed
    in the app with its code, and confirmed by the super admin against their M-Pesa SMS. Only a
    confirmed settlement is written to the ledger."""

    __tablename__ = "settlements"
    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_positive"),
        one_of("status", ("pending", "confirmed", "rejected")),
        CheckConstraint(
            "(status = 'confirmed') = (confirmed_at IS NOT NULL)", name="confirmed_at_iff_confirmed"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id"), index=True)
    statement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("statements.id"))
    amount: Mapped[int] = mapped_column(Integer)
    mpesa_code: Mapped[str] = mapped_column(String(12), unique=True)
    status: Mapped[str] = mapped_column(String(10), default="pending", server_default="pending")
    claimed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str | None] = mapped_column(String(200))  # why it was rejected
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()


class RiderPayout(Base):
    __tablename__ = "rider_payouts"
    __table_args__ = (CheckConstraint("amount > 0", name="amount_positive"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    amount: Mapped[int] = mapped_column(Integer)
    mpesa_code: Mapped[str] = mapped_column(String(12), unique=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()
