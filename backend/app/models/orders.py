import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, non_negative, one_of, updated_at, uuid_pk
from app.models.enums import (
    ACTOR_TYPES,
    ORDER_STATUSES,
    ORDER_TYPES,
    PAYMENT_METHODS,
    RIDER_FEE_MODES,
)


class Customer(Base):
    __tablename__ = "customers"

    phone: Mapped[str] = mapped_column(String(12), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    completed_orders: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Stamp-card rewards are counted from orders (bonus_kind = 'stamp'); see services/bonus.py.
    option_b_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    blocklisted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    trusted: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_order_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        one_of("type", ORDER_TYPES),
        one_of("rider_fee_mode", RIDER_FEE_MODES),
        one_of("payment_method", PAYMENT_METHODS),
        one_of("status", ORDER_STATUSES),
        *non_negative(
            "items_total",
            "order_discount",
            "food_net",
            "service_fee",
            "rider_fee",
            "rider_fee_in_till",
            "till_amount",
            "commission_amount",
            "platform_bonus",
            "eat_in_fee",
        ),
        CheckConstraint("eat_in_fee <= service_fee", name="eat_in_fee_within_service_fee"),
        CheckConstraint("food_net = items_total - order_discount", name="food_net_sum"),
        CheckConstraint(
            "till_amount = food_net + service_fee + rider_fee_in_till - platform_bonus",
            name="till_amount_sum",
        ),
        CheckConstraint(
            "(bonus_kind IS NULL AND platform_bonus = 0)"
            " OR (bonus_kind IN ('stamp', 'free_delivery') AND platform_bonus > 0)",
            name="bonus_kind_amount",
        ),
        CheckConstraint(
            "(rider_fee_mode = 'included' AND rider_fee_in_till = rider_fee)"
            " OR (rider_fee_mode <> 'included' AND rider_fee_in_till = 0)",
            name="rider_fee_in_till_by_mode",
        ),
        CheckConstraint(
            "(type = 'pickup' AND rider_fee_mode = 'none' AND rider_fee = 0)"
            " OR (type = 'eat_in' AND rider_fee_mode = 'none' AND rider_fee = 0"
            " AND payment_method = 'mpesa' AND arrive_at IS NOT NULL)"
            " OR (type = 'delivery' AND rider_fee_mode IN ('included', 'cash')"
            " AND payment_method = 'mpesa' AND lat IS NOT NULL AND lng IS NOT NULL)",
            name="type_rules",
        ),
        CheckConstraint("commission_bp BETWEEN 0 AND 10000", name="commission_bp_range"),
        CheckConstraint("commission_amount <= food_net", name="commission_within_food"),
        CheckConstraint(
            "customer_fee_answer IS NULL OR customer_fee_answer IN ('yes', 'no')",
            name="customer_fee_answer",
        ),
        Index("ix_orders_hotel_status_created", "hotel_id", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(12), unique=True)
    tracking_token: Mapped[str] = mapped_column(String(64), unique=True)
    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id"))
    customer_phone: Mapped[str] = mapped_column(ForeignKey("customers.phone"), index=True)
    customer_name: Mapped[str] = mapped_column(String(120))
    type: Mapped[str] = mapped_column(String(8))
    rider_fee_mode: Mapped[str] = mapped_column(String(8))
    payment_method: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(20))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    landmark: Mapped[str | None] = mapped_column(String(300))
    # Hotel -> customer distance the rider fee was priced on (km, 1 decimal). DECISIONS D16.
    distance_km: Mapped[float | None] = mapped_column(Float)

    # Money snapshot, whole KES (spec section 12).
    items_total: Mapped[int] = mapped_column(Integer)
    order_discount: Mapped[int] = mapped_column(Integer)
    food_net: Mapped[int] = mapped_column(Integer)
    service_fee: Mapped[int] = mapped_column(Integer)
    rider_fee: Mapped[int] = mapped_column(Integer)
    rider_fee_in_till: Mapped[int] = mapped_column(Integer)
    till_amount: Mapped[int] = mapped_column(Integer)
    commission_bp: Mapped[int] = mapped_column(Integer)
    commission_amount: Mapped[int] = mapped_column(Integer)
    discount_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("discounts.id"))
    # Platform-funded bonus (DECISIONS D19): lowers what the customer pays; the platform owes
    # the hotel this amount (ledger bonus_credit), so the hotel's food sale stays whole.
    platform_bonus: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Eat in (D28): the owner's markup, already inside service_fee (platform money, so the
    # ledger and statements treat it as service fee); kept apart only to show it.
    eat_in_fee: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    arrive_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bonus_kind: Mapped[str | None] = mapped_column(String(16))

    customer_trans_code: Mapped[str | None] = mapped_column(String(12))
    delivery_code: Mapped[str | None] = mapped_column(String(4))
    rider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    # Delivery (DECISIONS D21). Option A instant: hotel hands the fee over with the food and
    # both sides confirm; the ledger entry is written once both have.
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # The rider has seen this job (took it, tapped "Got it", or acted on it). An assignment by
    # the admin rings the rider until then (D23).
    rider_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fee_hotel_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fee_rider_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_code_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Option B "fee not paid" (D8): rider claims after delivery; the customer is asked.
    fee_not_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    customer_fee_answer: Mapped[str | None] = mapped_column(String(3))  # yes | no
    prep_minutes: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(String(300))  # reject / cancel / failure reason
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preparing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picked_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    on_the_way_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    collected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # any exit status


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        CheckConstraint("quantity BETWEEN 1 AND 20", name="quantity_range"),
        *non_negative("unit_price", "options_price", "line_discount", "line_total"),
        CheckConstraint(
            "line_total = (unit_price + options_price) * quantity - line_discount",
            name="line_total_sum",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"))
    name_snapshot: Mapped[str] = mapped_column(String(120))
    unit_price: Mapped[int] = mapped_column(Integer)
    options_snapshot: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    options_price: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[int] = mapped_column(Integer)
    line_discount: Mapped[int] = mapped_column(Integer)
    line_total: Mapped[int] = mapped_column(Integer)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("orders.id"))
    created_at: Mapped[datetime] = created_at()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (UniqueConstraint("discount_id", "phone"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    discount_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("discounts.id"))
    phone: Mapped[str] = mapped_column(String(12))
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"))
    created_at: Mapped[datetime] = created_at()


class OrderEvent(Base):
    """Append-only status history (a DB trigger rejects UPDATE and DELETE)."""

    __tablename__ = "order_events"
    __table_args__ = (one_of("actor_type", ACTOR_TYPES),)

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    actor_type: Mapped[str] = mapped_column(String(12))
    actor_id: Mapped[uuid.UUID | None] = mapped_column()
    reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = created_at()


class Rating(Base):
    """Customer's stars for one completed order (D28): the hotel always, the rider on
    deliveries. One per order."""

    __tablename__ = "ratings"
    __table_args__ = (
        CheckConstraint("hotel_stars BETWEEN 1 AND 5", name="hotel_stars_range"),
        CheckConstraint(
            "rider_stars IS NULL OR rider_stars BETWEEN 1 AND 5", name="rider_stars_range"
        ),
        CheckConstraint("(rider_stars IS NULL) = (rider_id IS NULL)", name="rider_with_stars"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), unique=True)
    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id"), index=True)
    rider_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    hotel_stars: Mapped[int] = mapped_column(SmallInteger)
    rider_stars: Mapped[int | None] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = created_at()
