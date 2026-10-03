"""Platform-funded customer bonuses (DECISIONS D19).

- Stamp card: every `stamp_every`-th completed order earns `stamp_reward` KES off one order.
  Rewards are counted from orders, not stored: earned = completed // N, used = live orders that
  took a stamp. A cancelled, rejected or expired stamp order gives the stamp back by itself.
- Free delivery once food reaches `free_delivery_min_food` (option A only; see pricing).
- All bonuses stop for the day once `bonus_daily_budget` (Kenya day, all hotels) is used up.
  A bonus is only offered if it fits in what is left, so the budget is never exceeded.

Phone numbers are not verified (D9), so nothing here is given to a new number: a stamp needs
real orders that a hotel marked collected or a rider delivered.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Customer, Order
from app.services.pricing import Bonuses
from app.services.settings import PlatformSettings

EAT = timedelta(hours=3)
GONE = ("cancelled", "rejected", "expired")
LOCK_KEY = 7_315_019  # advisory lock: one bonus decision at a time (place only)


@dataclass(frozen=True)
class StampCard:
    every: int  # 0 = stamp card off
    have: int  # stamps towards the next reward (0..every)
    reward_ready: bool
    reward: int


def kenya_day_start(now: datetime) -> datetime:
    local = now + EAT
    return local.replace(hour=0, minute=0, second=0, microsecond=0) - EAT


async def stamps_used(session: AsyncSession, phone: str) -> int:
    stmt = (
        select(func.count())
        .select_from(Order)
        .where(
            Order.customer_phone == phone,
            Order.bonus_kind == "stamp",
            Order.status.not_in(GONE),
        )
    )
    return int(await session.scalar(stmt) or 0)


async def stamp_card(
    session: AsyncSession, s: PlatformSettings, customer: Customer | None
) -> StampCard:
    n = s.stamp_every if s.stamp_reward else 0
    if not n or customer is None:
        return StampCard(n, 0, False, s.stamp_reward)
    used = await stamps_used(session, customer.phone)
    ready = customer.completed_orders // n > used
    have = n if ready else max(customer.completed_orders - used * n, 0) % n
    return StampCard(n, have, ready, s.stamp_reward)


async def budget_left(session: AsyncSession, s: PlatformSettings, now: datetime) -> int:
    spent = await session.scalar(
        select(func.coalesce(func.sum(Order.platform_bonus), 0)).where(
            Order.created_at >= kenya_day_start(now), Order.status.not_in(GONE)
        )
    )
    return s.bonus_daily_budget - int(spent or 0)


async def offer(
    session: AsyncSession,
    s: PlatformSettings,
    customer: Customer | None,
    *,
    rider_fee: int,
    now: datetime,
    placing: bool,
) -> tuple[Bonuses, StampCard]:
    """What this customer may get on this order. When `placing`, takes a transaction-scoped
    lock so two orders can't both take the last of the budget or the same stamp."""
    if placing:
        await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
    card = await stamp_card(session, s, customer)
    left = await budget_left(session, s, now)
    stamp = s.stamp_reward if card.reward_ready and left >= s.stamp_reward else 0
    free_min = s.free_delivery_min_food if left >= rider_fee else 0
    return Bonuses(stamp_reward=stamp, free_delivery_min_food=free_min), card
