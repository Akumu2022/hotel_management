import uuid
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, one_of, updated_at, uuid_pk
from app.models.enums import HOTEL_STATUSES


class Hotel(Base):
    __tablename__ = "hotels"
    __table_args__ = (
        one_of("status", HOTEL_STATUSES),
        # Blank = use the global default; when set, same bounds as the global setting.
        CheckConstraint(
            "commission_bp IS NULL OR commission_bp BETWEEN 0 AND 5000", name="commission_bp_range"
        ),
        CheckConstraint("service_fee IS NULL OR service_fee >= 0", name="service_fee_non_negative"),
        CheckConstraint("(lat IS NULL) = (lng IS NULL)", name="location_both_or_none"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    phone: Mapped[str] = mapped_column(String(12))
    till_number: Mapped[str] = mapped_column(String(20), unique=True)
    commission_bp: Mapped[int | None] = mapped_column(Integer)
    service_fee: Mapped[int | None] = mapped_column(Integer)
    cash_pickup_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    accepting_orders: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    pause_reason: Mapped[str | None] = mapped_column(String(200))
    cover_image_key: Mapped[str | None] = mapped_column(String(200))
    accent_color: Mapped[str | None] = mapped_column(String(7))
    # Where riders collect from; distance-based rider fees are measured from here.
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = created_at()
    updated_at: Mapped[datetime] = updated_at()


class HotelHours(Base):
    __tablename__ = "hotel_hours"
    __table_args__ = (
        UniqueConstraint("hotel_id", "weekday"),
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    hotel_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hotels.id", ondelete="CASCADE"))
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday
    opens_at: Mapped[time] = mapped_column(Time)
    closes_at: Mapped[time] = mapped_column(Time)
