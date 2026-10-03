import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, created_at, one_of, uuid_pk
from app.models.enums import HOTEL_ROLES, KYC_STATUSES, PAYOUT_MODES, USER_ROLES

_HOTEL_ROLE_LIST = ", ".join(f"'{r}'" for r in HOTEL_ROLES)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        one_of("role", USER_ROLES),
        CheckConstraint(
            f"(role IN ({_HOTEL_ROLE_LIST})) = (hotel_id IS NOT NULL)",
            name="hotel_id_iff_hotel_role",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    role: Mapped[str] = mapped_column(String(16))
    hotel_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("hotels.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(12), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = created_at()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at()


class RiderProfile(Base):
    """Rider KYC (DECISIONS D21). The super admin reviews every application; only approved
    riders see or take jobs. ID photos and the selfie are private files (never public URLs)."""

    __tablename__ = "rider_profiles"
    __table_args__ = (
        one_of("payout_mode", PAYOUT_MODES),
        one_of("kyc_status", KYC_STATUSES),
        CheckConstraint(
            "kyc_status = 'draft' OR (id_front_key IS NOT NULL AND id_back_key IS NOT NULL"
            " AND selfie_key IS NOT NULL AND consent_at IS NOT NULL)",
            name="submitted_complete",
        ),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    national_id: Mapped[str] = mapped_column(String(20), unique=True)
    mpesa_number: Mapped[str] = mapped_column(String(12))
    next_of_kin: Mapped[str] = mapped_column(String(200))  # next of kin's full name
    next_of_kin_phone: Mapped[str | None] = mapped_column(String(12))
    residence_area: Mapped[str | None] = mapped_column(String(200))
    # Private storage keys (not under the public media folder).
    id_front_key: Mapped[str | None] = mapped_column(String(200))
    id_back_key: Mapped[str | None] = mapped_column(String(200))
    selfie_key: Mapped[str | None] = mapped_column(String(200))
    # Small public photo made from the selfie: customers see who is coming.
    photo_key: Mapped[str | None] = mapped_column(String(200))
    consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kyc_status: Mapped[str] = mapped_column(String(10), default="draft", server_default="draft")
    kyc_note: Mapped[str | None] = mapped_column(String(300))  # rejection / suspension reason
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payout_mode: Mapped[str] = mapped_column(String(8), default="instant", server_default="instant")
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RiderStrike(Base):
    """A rider-fault failed delivery (D7). Two in 30 days suspends the rider."""

    __tablename__ = "rider_strikes"

    id: Mapped[uuid.UUID] = uuid_pk()
    rider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), unique=True)
    reason: Mapped[str] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = created_at()


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    endpoint: Mapped[str] = mapped_column(String(1000), unique=True)
    keys: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at()
