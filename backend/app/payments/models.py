"""Own tables in the `payments` schema. Nothing here has a foreign key into the pilot tables:
orders and parties are plain ids, so the module can be lifted out later."""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    MetaData,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "payments"
BUCKETS = ("pending", "available", "reserved", "paid")
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
