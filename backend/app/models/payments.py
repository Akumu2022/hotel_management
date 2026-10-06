import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, non_negative, one_of, uuid_pk
from app.models.enums import (
    PAYMENT_SOURCES,
    PAYMENT_STATUSES,
    REFUND_STATUSES,
    REVIEW_STATUSES,
    REVIEW_TYPES,
    SMS_PARSE_STATUSES,
)


class ForwarderDevice(Base):
    __tablename__ = "forwarder_devices"
    __table_args__ = (
        Index(
            "uq_forwarder_devices_till_number_active",
            "till_number",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    hotel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hotels.id"))  # null = platform
    label: Mapped[str] = mapped_column(String(80))
    till_number: Mapped[str] = mapped_column(String(20))
    sim_slot: Mapped[int | None] = mapped_column(SmallInteger)
    secret_encrypted: Mapped[str] = mapped_column(String(300))
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
    # What the phone last reported, for the "Till phone" status screens.
    app_version: Mapped[str | None] = mapped_column(String(20))
    last_sms_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_report: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class ForwarderPairing(Base):
    """A one-time code shown on screen to pair a Till phone. Only its hash is kept."""

    __tablename__ = "forwarder_pairings"

    id: Mapped[uuid.UUID] = uuid_pk()
    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    device_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("forwarder_devices.id"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()


class DeviceNonce(Base):
    __tablename__ = "device_nonces"
    __table_args__ = (UniqueConstraint("device_id", "nonce"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forwarder_devices.id"))
    nonce: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = created_at()


class SmsMessage(Base):
    """Raw M-Pesa SMS from a forwarder, kept permanently as dispute evidence."""

    __tablename__ = "sms_messages"
    __table_args__ = (one_of("parse_status", SMS_PARSE_STATUSES),)

    id: Mapped[uuid.UUID] = uuid_pk()
    device_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("forwarder_devices.id"), index=True)
    message_id: Mapped[str] = mapped_column(String(64), unique=True)
    raw_text: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    parse_status: Mapped[str] = mapped_column(String(10))
    trans_code: Mapped[str | None] = mapped_column(String(12), index=True)
    amount: Mapped[int | None] = mapped_column(Integer)
    sender_name: Mapped[str | None] = mapped_column(String(120))
    phone_digits: Mapped[str | None] = mapped_column(String(16))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        one_of("source", PAYMENT_SOURCES),
        one_of("status", PAYMENT_STATUSES),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            "name_match IS NULL OR name_match BETWEEN 0 AND 2", name="name_match_range"
        ),
        Index(
            "uq_payments_order_id",
            "order_id",
            unique=True,
            postgresql_where=text("order_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    till_number: Mapped[str] = mapped_column(String(20))
    trans_code: Mapped[str] = mapped_column(String(12), unique=True)
    amount: Mapped[int] = mapped_column(Integer)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(10))
    sms_message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sms_messages.id"))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"))
    settlement_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("settlements.id"))
    status: Mapped[str] = mapped_column(String(10))
    # The payer's name from the Till SMS and how well it matches the checkout name
    # (2 = two names, 1 = one name, 0 = none, null = unknown, e.g. typed by the cashier).
    payer_name: Mapped[str | None] = mapped_column(String(120))
    name_match: Mapped[int | None] = mapped_column(SmallInteger)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (
        one_of("type", REVIEW_TYPES),
        one_of("status", REVIEW_STATUSES),
        Index("ix_review_items_hotel_status", "hotel_id", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    type: Mapped[str] = mapped_column(String(20))
    hotel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hotels.id"))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"))
    payment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("payments.id"))
    sms_message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sms_messages.id"))
    reason: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10), default="open", server_default="open")
    resolution: Mapped[str | None] = mapped_column(String(300))
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class Refund(Base):
    """One approved refund. split into food / service fee / rider fee parts so commission
    can be reversed pro rata; excess_amount returns an overpayment. Total per order <= amount
    paid is checked under a row lock on the order."""

    __tablename__ = "refunds"
    __table_args__ = (
        one_of("status", REFUND_STATUSES),
        CheckConstraint("amount > 0", name="amount_positive"),
        *non_negative("food_amount", "service_fee_amount", "rider_fee_amount", "excess_amount"),
        CheckConstraint(
            "amount = food_amount + service_fee_amount + rider_fee_amount + excess_amount",
            name="parts_sum",
        ),
        CheckConstraint("(status = 'sent') = (mpesa_code IS NOT NULL)", name="sent_has_code"),
        Index(
            "uq_refunds_mpesa_code",
            "mpesa_code",
            unique=True,
            postgresql_where=text("mpesa_code IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    food_amount: Mapped[int] = mapped_column(Integer)
    service_fee_amount: Mapped[int] = mapped_column(Integer)
    rider_fee_amount: Mapped[int] = mapped_column(Integer)
    excess_amount: Mapped[int] = mapped_column(Integer)  # overpayment returned
    reason: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(10), default="approved", server_default="approved")
    mpesa_code: Mapped[str | None] = mapped_column(String(12))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    sent_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()
