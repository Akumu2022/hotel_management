"""Own tables in the `payments` schema. Nothing here has a foreign key into the pilot tables:
orders and parties are plain ids, so the module can be lifted out later."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "payments"
BUCKETS = ("pending", "available", "reserved", "paid", "earned")
PARTY_TYPES = ("rider", "hotel", "platform")


class PBase(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class WalletEntry(PBase):
    """Append-only. A balance is the SUM of signed amounts per (party, bucket); a move between
    buckets is two entries sharing a `group_id`. Corrections are new entries."""

    __tablename__ = "wallet_entries"
    __table_args__ = (
        CheckConstraint(f"bucket IN ({', '.join(repr(b) for b in BUCKETS)})", name="bucket"),
        CheckConstraint(
            f"party_type IN ({', '.join(repr(p) for p in PARTY_TYPES)})", name="party_type"
        ),
        CheckConstraint("amount <> 0", name="amount_nonzero"),
        Index("ix_wallet_party", "party_type", "party_id", "bucket", "shadow"),
        Index("ix_wallet_order", "order_ref"),
    )

    id: Mapped[uuid.UUID] = _pk()
    idem_key: Mapped[str] = mapped_column(String(120), unique=True)
    group_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    party_type: Mapped[str] = mapped_column(String(10))
    party_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    bucket: Mapped[str] = mapped_column(String(10))
    amount: Mapped[int] = mapped_column(BigInteger)  # signed KES
    kind: Mapped[str] = mapped_column(String(30))
    order_ref: Mapped[str | None] = mapped_column(String(40))
    shadow: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class OutboxEvent(PBase):
    """Events out, not shared tables. Read in-process today, a queue later."""

    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = _pk()
    topic: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))


STK_STATUSES = ("created", "sent", "failed", "success", "cancelled", "review")


class StkRequest(PBase):
    """One STK Push attempt. CheckoutRequestID is unique; a receipt can be used only once."""

    __tablename__ = "stk_requests"
    __table_args__ = (
        CheckConstraint(f"status IN ({', '.join(repr(x) for x in STK_STATUSES)})", name="status"),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_stk_order", "order_ref"),
        Index(
            "uq_stk_receipt", "receipt", unique=True, postgresql_where=text("receipt IS NOT NULL")
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    order_ref: Mapped[str] = mapped_column(String(40))
    phone: Mapped[str] = mapped_column(String(16))
    amount: Mapped[int] = mapped_column(Integer)
    # Part of `amount` that is the rider's fee: held on success, credited to whoever delivers.
    rider_fee: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    hotel_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    hotel_share: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    platform_fee: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(10), server_default=text("'created'"))
    checkout_request_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    merchant_request_id: Mapped[str | None] = mapped_column(String(80))
    receipt: Mapped[str | None] = mapped_column(String(20))
    result_code: Mapped[int | None] = mapped_column(Integer)
    result_desc: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RawCallback(PBase):
    """Every callback body, stored first and processed after. A duplicate is stored once."""

    __tablename__ = "raw_callbacks"
    __table_args__ = (UniqueConstraint("kind", "external_id"),)

    id: Mapped[uuid.UUID] = _pk()
    kind: Mapped[str] = mapped_column(String(20))
    external_id: Mapped[str] = mapped_column(String(120))
    body: Mapped[dict] = mapped_column(JSONB)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


PAYOUT_STATUSES = (
    "queued",
    "submitted",
    "succeeded",
    "failed",
    "unknown",
    "manual_review",
)
PAYOUT_KINDS = ("auto", "withdraw", "withdraw_extra")


class Payout(PBase):
    """One B2C payment to a rider. OriginatorConversationID is this row's id, so Daraja can
    never be asked to pay the same row twice. A timeout is `unknown` and is NEVER resent: a
    retry after a confirmed failure is a new row pointing at the old one (retry_of)."""

    __tablename__ = "payouts"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(x) for x in PAYOUT_STATUSES)})", name="status"
        ),
        CheckConstraint(f"kind IN ({', '.join(repr(x) for x in PAYOUT_KINDS)})", name="kind"),
        CheckConstraint("amount > 0 AND charge >= 0", name="amounts"),
        # One automatic-or-free payout per rider per day: a job run twice cannot pay twice.
        Index(
            "uq_payout_rider_day",
            "rider_id",
            "payout_date",
            unique=True,
            postgresql_where=text("kind IN ('auto', 'withdraw') AND status <> 'failed'"),
        ),
        Index("ix_payout_status", "status"),
    )

    id: Mapped[uuid.UUID] = _pk()
    rider_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    kind: Mapped[str] = mapped_column(String(16))
    payout_date: Mapped[date] = mapped_column(Date)
    phone: Mapped[str] = mapped_column(String(16))
    amount: Mapped[int] = mapped_column(Integer)  # what the rider receives
    charge: Mapped[int] = mapped_column(Integer, server_default=text("0"))  # taken from rider
    status: Mapped[str] = mapped_column(String(14), server_default=text("'queued'"))
    idem_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    retry_of: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    conversation_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    transaction_id: Mapped[str | None] = mapped_column(String(30), unique=True)
    result_code: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(300))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobRun(PBase):
    """A scheduled job's marker: (job, run_key) is unique, so a second run exits at once."""

    __tablename__ = "job_runs"
    __table_args__ = (UniqueConstraint("job", "run_key"),)

    id: Mapped[uuid.UUID] = _pk()
    job: Mapped[str] = mapped_column(String(40))
    run_key: Mapped[str] = mapped_column(String(40))
    detail: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


SETTLEMENT_CHANNELS = ("till", "phone")


class HotelSettlement(PBase):
    """A hotel's daily payout. One per hotel per day (statement_date); money is reserved when
    queued and follows the same never-twice rules as rider payouts. `detail` lists the orders
    the statement is made of, so the hotel can see exactly what it is being paid for."""

    __tablename__ = "hotel_settlements"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(x) for x in PAYOUT_STATUSES)})", name="status"
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index(
            "uq_settlement_hotel_day",
            "hotel_id",
            "statement_date",
            unique=True,
            postgresql_where=text("status <> 'failed'"),
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    hotel_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    statement_date: Mapped[date] = mapped_column(Date)
    channel: Mapped[str] = mapped_column(String(6))  # till (B2B) | phone (B2C)
    destination: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(14), server_default=text("'queued'"))
    detail: Mapped[list | None] = mapped_column(JSONB)  # [{"order_ref", "amount"}]
    conversation_id: Mapped[str | None] = mapped_column(String(80), unique=True)
    transaction_id: Mapped[str | None] = mapped_column(String(30), unique=True)
    result_code: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(300))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
