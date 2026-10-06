import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, ConfigDict, Field, field_validator, model_validator

from app.core.errors import AppError
from app.core.phone import normalize_phone
from app.models.enums import USER_ROLES
from app.schemas.common import Phone, Schema
from app.services.settings import (
    MAX_COMMISSION_BP,
    CommissionTier,
    PlatformSettings,
    RiderFeeBand,
    bp_to_percent,
    percent_to_bp,
)


def _percent_field_to_bp(value: float | None) -> int | None:
    if value is None:
        return None
    bp = percent_to_bp(value)
    if not 0 <= bp <= MAX_COMMISSION_BP:
        raise ValueError(f"Must be between 0 and {MAX_COMMISSION_BP // 100} %")
    return bp


def _check_percent(value: float) -> float:
    _percent_field_to_bp(value)
    return value


# Admins type 10 or 12.5; stored as basis points.
Percent = Annotated[float, AfterValidator(_check_percent)]


# --- Settings ---------------------------------------------------------------------------------


class SettingsOut(Schema):
    commission_mode: str
    commission_tiers: list[dict]
    commission_step: int
    commission_step_fee: int
    commission_percent: float
    service_fee: int
    eat_in_fee: int
    rider_fee_mode: str
    rider_fee_bands: list[dict]
    rider_fee_base: int
    rider_fee_per_km: int
    rider_fee_min: int
    rider_fee_max_km: float
    distance_method: str
    unpaid_expiry_minutes: int
    late_payment_grace_hours: int
    acceptance_alert_minutes: int
    acceptance_timeout_minutes: int
    first_time_cash_cap: int
    hotel_unpaid_limit: int
    hotel_overdue_days: int
    rider_compensation_weekly_cap: int
    order_cutoff_minutes: int
    rider_payout_default: str
    delivery_zone: list[list[float]]
    support_whatsapp: str
    platform_mpesa_number: str
    stamp_every: int
    stamp_reward: int
    free_delivery_min_food: int
    bonus_daily_budget: int
    unconfirmed: bool = Field(description="True until an admin has reviewed and saved once")

    @classmethod
    def build(cls, s: PlatformSettings, reviewed: bool) -> "SettingsOut":
        data = s.model_dump()
        data["commission_percent"] = bp_to_percent(data.pop("commission_bp"))
        return cls(**data, unconfirmed=not reviewed)


class SettingsIn(Schema):
    """Partial update. Whole-KES money fields reject decimals (strict int)."""

    model_config = ConfigDict(extra="forbid")
    commission_mode: Literal["tiers", "percent"] | None = None
    commission_tiers: list[CommissionTier] | None = Field(None, min_length=1, max_length=12)
    commission_step: int | None = Field(None, strict=True)
    commission_step_fee: int | None = Field(None, strict=True)
    commission_percent: Percent | None = None
    service_fee: int | None = Field(None, strict=True)
    eat_in_fee: int | None = Field(None, strict=True)
    rider_fee_bands: list[RiderFeeBand] | None = Field(None, min_length=1, max_length=8)
    rider_fee_mode: Literal["bands", "per_km"] | None = None
    rider_fee_base: int | None = Field(None, strict=True)
    rider_fee_per_km: int | None = Field(None, strict=True)
    rider_fee_min: int | None = Field(None, strict=True)
    rider_fee_max_km: float | None = None
    distance_method: Literal["road", "straight"] | None = None
    unpaid_expiry_minutes: int | None = Field(None, strict=True)
    late_payment_grace_hours: int | None = Field(None, strict=True)
    acceptance_alert_minutes: int | None = Field(None, strict=True)
    acceptance_timeout_minutes: int | None = Field(None, strict=True)
    first_time_cash_cap: int | None = Field(None, strict=True)
    hotel_unpaid_limit: int | None = Field(None, strict=True)
    hotel_overdue_days: int | None = Field(None, strict=True)
    rider_compensation_weekly_cap: int | None = Field(None, strict=True)
    order_cutoff_minutes: int | None = Field(None, strict=True)
    rider_payout_default: Literal["instant", "weekly"] | None = None
    support_whatsapp: str | None = Field(None, max_length=20)  # blank removes it
    platform_mpesa_number: str | None = Field(None, max_length=20)
    delivery_zone: list[list[float]] | None = None
    stamp_every: int | None = Field(None, strict=True)
    stamp_reward: int | None = Field(None, strict=True)
    free_delivery_min_food: int | None = Field(None, strict=True)
    bonus_daily_budget: int | None = Field(None, strict=True)

    @field_validator("delivery_zone")
    @classmethod
    def _zone(cls, v):
        if v is None or v == []:
            return v
        if len(v) < 3 or any(len(p) != 2 for p in v):
            raise ValueError("Zone must be at least 3 [lng, lat] points")
        return v

    @field_validator("platform_mpesa_number")
    @classmethod
    def _platform_number(cls, v):
        return v if v is None else normalize_phone(v)

    @field_validator("support_whatsapp")
    @classmethod
    def _whatsapp(cls, v):
        if v is None or v.strip() == "":
            return v if v is None else ""
        return normalize_phone(v)

    def to_changes(self) -> dict:
        changes = self.model_dump(exclude_unset=True, exclude_none=True)
        if "commission_percent" in changes:
            changes["commission_bp"] = _percent_field_to_bp(changes.pop("commission_percent"))
        return changes


# --- Hotels -----------------------------------------------------------------------------------


class HotelOut(Schema):
    id: uuid.UUID
    name: str
    slug: str
    phone: str
    till_number: str
    commission_percent: float | None
    service_fee: int | None
    cash_pickup_enabled: bool
    accepting_orders: bool
    status: str
    pause_reason: str | None
    accent_color: str | None
    lat: float | None = None
    lng: float | None = None
    created_at: datetime
    rating: float | None = None
    rating_count: int = 0

    @model_validator(mode="before")
    @classmethod
    def _from_model(cls, obj):
        if hasattr(obj, "commission_bp"):
            data = {k: getattr(obj, k) for k in cls.model_fields if hasattr(obj, k)}
            bp = obj.commission_bp
            data["commission_percent"] = None if bp is None else bp_to_percent(bp)
            return data
        return obj


_SLUG = r"^[a-z0-9]+(-[a-z0-9]+)*$"
_TILL = r"^\d{5,10}$"
_COLOR = r"^#[0-9a-fA-F]{6}$"


class HotelLoginIn(Schema):
    """The hotel admin's login, made with the hotel."""

    name: str = Field(min_length=2, max_length=120)
    phone: Phone
    password: str = Field(min_length=8, max_length=200)


class HotelCreate(Schema):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=2, max_length=80, pattern=_SLUG)
    phone: Phone
    till_number: str = Field(pattern=_TILL)
    commission_percent: Percent | None = None  # blank = global default
    service_fee: int | None = Field(None, ge=0, strict=True)
    cash_pickup_enabled: bool = True
    accent_color: str | None = Field(None, pattern=_COLOR)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    admin: HotelLoginIn | None = None

    @model_validator(mode="after")
    def _location_pair(self):
        if (self.lat is None) != (self.lng is None):
            raise ValueError("Set both latitude and longitude, or neither")
        return self


class HotelPatch(Schema):
    name: str | None = Field(None, min_length=2, max_length=120)
    phone: Phone | None = None
    till_number: str | None = Field(None, pattern=_TILL)
    commission_percent: Percent | None = None  # explicit null clears the override
    service_fee: int | None = Field(None, ge=0, strict=True)
    cash_pickup_enabled: bool | None = None
    accepting_orders: bool | None = None
    status: Literal["active", "paused"] | None = None
    pause_reason: str | None = Field(None, max_length=200)
    accent_color: str | None = Field(None, pattern=_COLOR)
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)

    @model_validator(mode="after")
    def _location_pair(self):
        if (self.lat is None) != (self.lng is None):
            raise ValueError("Set both latitude and longitude, or neither")
        return self


_NULLABLE_HOTEL_FIELDS = {
    "commission_percent",
    "service_fee",
    "pause_reason",
    "accent_color",
    "lat",
    "lng",
}


def hotel_values(body: HotelCreate | HotelPatch) -> dict:
    """Request fields -> model column values, converting % to basis points."""
    data = body.model_dump(exclude_unset=True, exclude={"admin"})
    for key, value in data.items():
        if value is None and key not in _NULLABLE_HOTEL_FIELDS:
            raise AppError(422, "validation_error", f"{key} cannot be empty")
    if "commission_percent" in data:
        data["commission_bp"] = _percent_field_to_bp(data.pop("commission_percent"))
    return data


# --- Users ------------------------------------------------------------------------------------


class UserOut(Schema):
    id: uuid.UUID
    role: str
    hotel_id: uuid.UUID | None
    name: str
    phone: str
    is_active: bool
    created_at: datetime


class UserCreate(Schema):
    role: Literal[USER_ROLES]  # type: ignore[valid-type]
    hotel_id: uuid.UUID | None = None
    name: str = Field(min_length=2, max_length=120)
    phone: Phone
    password: str = Field(min_length=8, max_length=200)

    @model_validator(mode="after")
    def _hotel_for_hotel_roles(self):
        needs_hotel = self.role in ("hotel_admin", "cashier")
        if needs_hotel != (self.hotel_id is not None):
            raise ValueError("hotel_id is required for hotel roles and not allowed otherwise")
        return self


class UserPatch(Schema):
    name: str | None = Field(None, min_length=2, max_length=120)
    is_active: bool | None = None
    password: str | None = Field(None, min_length=8, max_length=200)
