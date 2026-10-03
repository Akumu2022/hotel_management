import uuid
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, non_negative, one_of, updated_at, uuid_pk
from app.models.enums import DISCOUNT_KINDS, DISCOUNT_SCOPES


class Category(Base):
    __tablename__ = "categories"
    __table_args__ = (UniqueConstraint("hotel_id", "name"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_from: Mapped[time | None] = mapped_column(Time)
    available_to: Mapped[time | None] = mapped_column(Time)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        *non_negative("price"),
        CheckConstraint("prep_minutes > 0", name="prep_minutes_positive"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id"), index=True)
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("categories.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    price: Mapped[int] = mapped_column(Integer)
    prep_minutes: Mapped[int] = mapped_column(Integer, default=15, server_default="15")
    is_sold_out: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    image_key: Mapped[str | None] = mapped_column(String(200))
    thumb_key: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class ProductOption(Base):
    __tablename__ = "product_options"
    __table_args__ = tuple(non_negative("price_delta"))

    id: Mapped[uuid.UUID] = uuid_pk()
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("products.id"), index=True)
    group_name: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(80))
    price_delta: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class Discount(Base):
    __tablename__ = "discounts"
    __table_args__ = (
        one_of("scope", DISCOUNT_SCOPES),
        one_of("kind", DISCOUNT_KINDS),
        CheckConstraint("value > 0", name="value_positive"),
        CheckConstraint("kind <> 'percent' OR value <= 10000", name="percent_max_100"),
        CheckConstraint("(scope = 'item') = (product_id IS NOT NULL)", name="product_iff_item"),
        CheckConstraint("max_uses IS NULL OR max_uses > 0", name="max_uses_positive"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ends_after_starts"),
        CheckConstraint("days_mask IS NULL OR days_mask BETWEEN 1 AND 127", name="days_mask_range"),
        CheckConstraint(
            "(daily_from IS NULL AND daily_to IS NULL)"
            " OR (daily_from BETWEEN 0 AND 1439 AND daily_to BETWEEN 1 AND 1440"
            " AND daily_to > daily_from)",
            name="daily_window",
        ),
        *non_negative("min_spend"),
        Index(
            "uq_discounts_hotel_id_promo_code",
            "hotel_id",
            "promo_code",
            unique=True,
            postgresql_where=text("promo_code IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id"), index=True)
    scope: Mapped[str] = mapped_column(String(8))
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    kind: Mapped[str] = mapped_column(String(8))
    # percent: basis points (1000 = 10 %); fixed: whole KES
    value: Mapped[int] = mapped_column(Integer)
    min_spend: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    promo_code: Mapped[str | None] = mapped_column(String(32))  # stored upper-case
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Happy hour (DECISIONS D19), Kenya time: weekdays bitmask (Mon = 1 ... Sun = 64) and a
    # daily window in minutes from midnight. NULL = every day / all day.
    days_mask: Mapped[int | None] = mapped_column(Integer)
    daily_from: Mapped[int | None] = mapped_column(Integer)
    daily_to: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_at()


class Offer(Base):
    __tablename__ = "offers"

    id: Mapped[uuid.UUID] = uuid_pk()
    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id"), index=True)
    title: Mapped[str] = mapped_column(String(120))
    image_key: Mapped[str | None] = mapped_column(String(200))
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.id"))
    discount_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("discounts.id"))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
