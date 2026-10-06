"""Admin-entered business settings.

Stored one row per key in `settings`. Percentages are stored as basis points and money as whole
KES. Admins type percentages as plain numbers (10, 12.5); `percent_to_bp` converts them.
Every change is audit-logged and only affects orders placed afterwards (orders snapshot values).
"""

import math
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Hotel, Setting
from app.services import audit

REVIEWED_KEY = "_reviewed"  # set once an admin has saved the settings (clears the banner)

MAX_COMMISSION_BP = 5000  # 50 %


class RiderFeeBand(BaseModel):
    """Deliveries up to `max_km` from the hotel cost `fee` KES."""

    model_config = ConfigDict(extra="forbid")

    max_km: float = Field(gt=0, le=50)
    fee: int = Field(ge=0, le=10_000, strict=True)


class CommissionTier(BaseModel):
    """Orders whose food total is at most `up_to` KES pay a flat `fee` KES commission."""

    model_config = ConfigDict(extra="forbid")

    up_to: int = Field(gt=0, le=10_000_000, strict=True)
    fee: int = Field(ge=0, le=100_000, strict=True)


# Owner's tiers: on the food total only, excluding service and rider fees.
DEFAULT_TIERS = [
    CommissionTier(up_to=500, fee=20),
    CommissionTier(up_to=1000, fee=30),
    CommissionTier(up_to=2000, fee=40),
    CommissionTier(up_to=3000, fee=50),
    CommissionTier(up_to=4000, fee=60),
    CommissionTier(up_to=5000, fee=70),
]


def tier_fee(food: int, tiers: tuple[tuple[int, int], ...], step: int, step_fee: int) -> int:
    """Flat commission for a food total. Above the last tier, `step_fee` more for every started
    `step` KES (5,001-6,000 -> +10, 6,001-7,000 -> +20 ...). Never more than the food itself."""
    if food <= 0:
        return 0
    for up_to, fee in tiers:
        if food <= up_to:
            return min(fee, food)
    last_up_to, last_fee = tiers[-1]
    extra_steps = -(-(food - last_up_to) // step)  # ceil
    return min(last_fee + extra_steps * step_fee, food)


DEFAULT_BANDS = [
    RiderFeeBand(max_km=2, fee=100),
    RiderFeeBand(max_km=5, fee=150),
    RiderFeeBand(max_km=10, fee=200),
]


class PlatformSettings(BaseModel):
    """Validated global settings. Field names are the keys stored in the `settings` table."""

    model_config = ConfigDict(extra="forbid")

    # "tiers" = flat fee by food total; "percent" = commission_bp of the food total.
    commission_mode: str = Field("tiers", pattern="^(tiers|percent)$")
    commission_tiers: list[CommissionTier] = Field(
        default_factory=lambda: list(DEFAULT_TIERS), min_length=1, max_length=12
    )
    commission_step: int = Field(1000, ge=1, le=1_000_000, strict=True)
    commission_step_fee: int = Field(10, ge=0, le=100_000, strict=True)
    commission_bp: int = Field(1000, ge=0, le=MAX_COMMISSION_BP)
    service_fee: int = Field(20, ge=0, le=10_000)
    # Eat in: the owner's markup on each eat-in order, platform money. 0 = none.
    eat_in_fee: int = Field(30, ge=0, le=10_000, strict=True)
    # Rider fee: "bands" = fixed price per distance band;
    # "per_km" = base + per-km price, never below the minimum, rounded up to KES 10.
    rider_fee_mode: str = Field("per_km", pattern="^(bands|per_km)$")
    rider_fee_bands: list[RiderFeeBand] = Field(
        default_factory=lambda: list(DEFAULT_BANDS), min_length=1, max_length=8
    )
    rider_fee_base: int = Field(50, ge=0, le=10_000, strict=True)
    rider_fee_per_km: int = Field(20, ge=0, le=2_000, strict=True)
    rider_fee_min: int = Field(100, ge=0, le=10_000, strict=True)
    rider_fee_max_km: float = Field(10, gt=0, le=100)  # per_km mode: furthest we deliver
    # How distance is measured: "road" (routing, with a straight-line fallback) or "straight".
    distance_method: str = Field("road", pattern="^(road|straight)$")
    unpaid_expiry_minutes: int = Field(20, ge=1, le=240)
    late_payment_grace_hours: int = Field(24, ge=1, le=168)
    acceptance_alert_minutes: int = Field(5, ge=1, le=60)
    acceptance_timeout_minutes: int = Field(10, ge=1, le=120)
    first_time_cash_cap: int = Field(1000, ge=0, le=1_000_000)
    hotel_unpaid_limit: int = Field(5000, ge=0, le=10_000_000)
    hotel_overdue_days: int = Field(3, ge=0, le=60)
    rider_compensation_weekly_cap: int = Field(2, ge=0, le=50)
    order_cutoff_minutes: int = Field(15, ge=0, le=180)
    rider_payout_default: str = Field("instant", pattern="^(instant|weekly)$")
    # WhatsApp number customers can message for help (2547XXXXXXXX); empty = not shown.
    support_whatsapp: str = Field("", pattern=r"^(|254[17]\d{8})$")
    # Where hotels send what they owe the platform: M-Pesa Send Money.
    platform_mpesa_number: str = Field("254742554713", pattern=r"^254[17]\d{8}$")
    # Bonuses, platform-funded. 0 turns each off.
    stamp_every: int = Field(5, ge=0, le=100, strict=True)  # every Nth completed order
    stamp_reward: int = Field(100, ge=0, le=10_000, strict=True)  # KES off that order
    free_delivery_min_food: int = Field(1500, ge=0, le=1_000_000, strict=True)
    bonus_daily_budget: int = Field(2000, ge=0, le=10_000_000, strict=True)  # all hotels
    # GeoJSON-style ring of [lng, lat] points drawn by the admin; empty until set.
    delivery_zone: list[list[float]] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bands_ascending(self):
        kms = [b.max_km for b in self.rider_fee_bands]
        if kms != sorted(kms) or len(set(kms)) != len(kms):
            raise ValueError("Rider fee distances must go up, e.g. 2 km, 5 km, 10 km")
        ups = [t.up_to for t in self.commission_tiers]
        if ups != sorted(ups) or len(set(ups)) != len(ups):
            raise ValueError("Commission tiers must go up, e.g. 500, 1000, 2000")
        return self

    @property
    def tiers(self) -> tuple[tuple[int, int], ...]:
        return tuple((t.up_to, t.fee) for t in self.commission_tiers)

    @property
    def max_delivery_km(self) -> float:
        if self.rider_fee_mode == "bands":
            return self.rider_fee_bands[-1].max_km
        return self.rider_fee_max_km

    def rider_fee_at(self, km: float) -> int | None:
        """The rider fee for a delivery distance, or None when it is beyond our range.
        The single place the fee is worked out: customer, hotel and rider all see this."""
        if km > self.max_delivery_km:
            return None
        if self.rider_fee_mode == "bands":
            return rider_fee_for(km, self.rider_fee_bands)
        raw = self.rider_fee_base + self.rider_fee_per_km * km
        return max(self.rider_fee_min, int(math.ceil(raw / 10) * 10))

    @property
    def base_rider_fee(self) -> int:
        """The lowest fee: shown as "from KES X" before the customer drops a pin."""
        return self.rider_fee_at(0) or 0


DEFAULTS = PlatformSettings()


def percent_to_bp(value: float | int | str) -> int:
    """'12.5' -> 1250. At most two decimal places; anything finer is rejected, not rounded."""
    try:
        d = Decimal(str(value))
    except InvalidOperation as e:
        raise ValueError("Enter a number, e.g. 10 or 12.5") from e
    bp = d * 100
    if bp != bp.to_integral_value():
        raise ValueError("Use at most two decimal places")
    return int(bp)


def bp_to_percent(bp: int) -> float:
    return bp / 100


async def load(session: AsyncSession) -> tuple[PlatformSettings, bool]:
    """Return (settings, reviewed). Missing keys fall back to the seeded defaults."""
    rows = (await session.execute(select(Setting))).scalars().all()
    stored = {r.key: r.value for r in rows}
    reviewed = bool(stored.pop(REVIEWED_KEY, False))
    known = {k: v for k, v in stored.items() if k in PlatformSettings.model_fields}
    return PlatformSettings(**{**DEFAULTS.model_dump(), **known}), reviewed


async def update(
    session: AsyncSession, changes: dict, actor_id: uuid.UUID | None
) -> PlatformSettings:
    """Validate and save changed keys, audit-logging old -> new. Caller commits."""
    current, _ = await load(session)
    merged = PlatformSettings(**{**current.model_dump(), **changes})  # raises ValidationError
    if merged.acceptance_alert_minutes >= merged.acceptance_timeout_minutes:
        raise ValueError("The duty alert must come before the acceptance timeout")

    old, new = current.model_dump(), merged.model_dump()
    for key in PlatformSettings.model_fields:
        if old[key] == new[key]:
            continue
        await _upsert(session, key, new[key], actor_id)
        await audit.log(
            session,
            actor_id=actor_id,
            action="settings.update",
            target_type="setting",
            target_id=key,
            details={"old": old[key], "new": new[key]},
        )
    await _upsert(session, REVIEWED_KEY, True, actor_id)
    return merged


async def _upsert(session: AsyncSession, key: str, value, actor_id: uuid.UUID | None) -> None:
    stmt = insert(Setting).values(key=key, value=value, updated_by=actor_id)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Setting.key],
        set_={"value": stmt.excluded.value, "updated_by": actor_id, "updated_at": func.now()},
    )
    await session.execute(stmt)


@dataclass(frozen=True)
class HotelRates:
    """The values a hotel's new orders snapshot: per-hotel override or global default."""

    commission_bp: int
    service_fee: int
    rider_fee: int
    eat_in_fee: int = 0
    # Flat tiers; empty = percent commission_bp. A per-hotel percent deal overrides tiers.
    commission_tiers: tuple[tuple[int, int], ...] = ()
    commission_step: int = 1000
    commission_step_fee: int = 10

    def commission_for(self, food: int) -> int:
        if self.commission_tiers:
            return tier_fee(
                food, self.commission_tiers, self.commission_step, self.commission_step_fee
            )
        return self.commission_bp * food // 10_000


def effective_for_hotel(settings: PlatformSettings, hotel: Hotel) -> HotelRates:
    service_fee = hotel.service_fee if hotel.service_fee is not None else settings.service_fee
    if hotel.commission_bp is None and settings.commission_mode == "tiers":
        return HotelRates(
            commission_bp=0,
            service_fee=service_fee,
            rider_fee=settings.base_rider_fee,
            eat_in_fee=settings.eat_in_fee,
            commission_tiers=settings.tiers,
            commission_step=settings.commission_step,
            commission_step_fee=settings.commission_step_fee,
        )
    return HotelRates(
        commission_bp=(
            hotel.commission_bp if hotel.commission_bp is not None else settings.commission_bp
        ),
        service_fee=service_fee,
        rider_fee=settings.base_rider_fee,
        eat_in_fee=settings.eat_in_fee,
    )


def seed_rows() -> list[dict]:
    """Rows inserted by the initial migration: the spec's proposed defaults, unreviewed."""
    rows = [{"key": k, "value": v} for k, v in DEFAULTS.model_dump().items()]
    rows.append({"key": REVIEWED_KEY, "value": False})
    return rows


def distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle (straight line) distance in km."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def rider_fee_for(distance: float, bands: list[RiderFeeBand]) -> int | None:
    """The first band that covers the distance, or None when it is beyond the last band."""
    for band in bands:
        if distance <= band.max_km:
            return band.fee
    return None
