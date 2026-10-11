"""The owner's view of one hotel: recent activity, commission standing, whether the map pin
is right, and signs a hotel may be keeping sales off the platform (which costs commission).

Signals are hints for the owner to look into, not proof. Each says what was seen and why it
matters. Thresholds are deliberately mild so a normal hotel shows nothing."""

import statistics
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog, Hotel, Order, RiderPing
from app.services import billing, settings

DONE = ("delivered", "collected")
BAD = ("rejected", "cancelled")
UNFINISHED = ("paid", "accepted", "preparing", "ready", "picked_up", "on_the_way")
STUCK_AFTER = timedelta(hours=3)
MIN_ORDERS = 10  # below this, rates are noise


def _flag(level: str, title: str, detail: str) -> dict:
    return {"level": level, "title": title, "detail": detail}


def _pct(a: float, b: float) -> float:
    return round(100 * a / b, 1) if b else 0.0


async def _platform_rates(session: AsyncSession, hotel_id, since: datetime) -> dict:
    """The same numbers across every OTHER hotel, so a hotel is judged against its peers."""
    paid = Order.paid_at.is_not(None)
    row = (
        await session.execute(
            select(
                func.count().filter(paid),
                func.count().filter(paid, Order.status.in_(BAD)),
                func.coalesce(func.sum(Order.order_discount).filter(paid), 0),
                func.coalesce(func.sum(Order.items_total).filter(paid), 0),
            ).where(Order.hotel_id != hotel_id, Order.created_at >= since)
        )
    ).one()
    paid_n, bad_n, disc, items = row
    return {"orders": paid_n, "bad_pct": _pct(bad_n, paid_n), "discount_pct": _pct(disc, items)}


async def _pickup_accuracy(session: AsyncSession, hotel: Hotel, orders: list[Order]) -> dict | None:
    """Where riders actually were when they collected: the best evidence of the true location."""
    fixes: list[tuple[float, float]] = []
    for o in [o for o in orders if o.picked_up_at and o.rider_id][:25]:
        pings = (
            await session.execute(
                select(RiderPing).where(
                    RiderPing.order_id == o.id,
                    RiderPing.at.between(
                        o.picked_up_at - timedelta(minutes=3), o.picked_up_at + timedelta(minutes=3)
                    ),
                )
            )
        ).scalars()
        good = [p for p in pings if p.accuracy_m is None or p.accuracy_m <= 100]
        if good:
            best = min(good, key=lambda p: abs((p.at - o.picked_up_at).total_seconds()))
            fixes.append((best.lat, best.lng))
    if len(fixes) < 3:
        return None
    lat = statistics.median(f[0] for f in fixes)
    lng = statistics.median(f[1] for f in fixes)
    out = {"samples": len(fixes), "lat": round(lat, 6), "lng": round(lng, 6), "off_by_m": None}
    if hotel.lat is not None:
        out["off_by_m"] = round(1000 * settings.distance_km(hotel.lat, hotel.lng, lat, lng))
    return out


async def overview(session: AsyncSession, hotel: Hotel, now: datetime) -> dict:
    d30, d14, d7 = now - timedelta(days=30), now - timedelta(days=14), now - timedelta(days=7)
    orders = list(
        (
            await session.execute(
                select(Order)
                .where(Order.hotel_id == hotel.id, Order.created_at >= d30)
                .order_by(Order.created_at.desc())
                .limit(3000)
            )
        ).scalars()
    )
    paid = [o for o in orders if o.paid_at]
    done = [o for o in paid if o.status in DONE]
    bad = [o for o in paid if o.status in BAD]
    sales = sum(o.food_net for o in done)
    waits = [
        (o.accepted_at - o.paid_at).total_seconds() / 60 for o in paid if o.accepted_at and o.paid_at
    ]
    stats = {
        "paid_orders": len(paid),
        "completed": len(done),
        "rejected_or_cancelled": len(bad),
        "sales": sales,
        "commission": sum(o.commission_amount for o in done),
        "avg_order": round(sales / len(done)) if done else 0,
        "median_accept_minutes": round(statistics.median(waits), 1) if waits else None,
        "last_7_days": sum(1 for o in paid if o.paid_at >= d7),
        "previous_7_days": sum(1 for o in paid if d14 <= o.paid_at < d7),
    }

    flags: list[dict] = []
    peers = await _platform_rates(session, hotel.id, d30)

    if hotel.lat is None:
        flags.append(
            _flag(
                "high",
                "No map location",
                "Customers cannot be delivered to or shown this hotel until it is pinned.",
            )
        )
    acc = await _pickup_accuracy(session, hotel, orders)
    if acc and acc["off_by_m"] is not None and acc["off_by_m"] > 300:
        flags.append(
            _flag(
                "medium",
                "Map pin looks wrong",
                f"Across {acc['samples']} pickups riders were about {acc['off_by_m']} m from the "
                "pinned spot. Delivery fees are measured from this pin. A suggested location is below.",
            )
        )

    bad_pct = _pct(len(bad), len(paid))
    if len(paid) >= MIN_ORDERS and bad_pct >= 15 and bad_pct > 2 * peers["bad_pct"]:
        flags.append(
            _flag(
                "high",
                "Many paid orders rejected or cancelled",
                f"{bad_pct}% of paid orders in 30 days (other hotels: {peers['bad_pct']}%). "
                "Ask why: customers may be told to order by phone instead.",
            )
        )

    stuck = [o for o in paid if o.status in UNFINISHED and now - o.paid_at > STUCK_AFTER]
    if stuck:
        flags.append(
            _flag(
                "high" if len(stuck) >= 3 else "medium",
                "Paid orders left unfinished",
                f"{len(stuck)} paid order(s) are over 3 hours old and never completed "
                f"(oldest {stuck[-1].code}). Commission is only counted on completed orders.",
            )
        )

    items = sum(o.items_total for o in paid)
    disc_pct = _pct(sum(o.order_discount for o in paid), items)
    if len(paid) >= MIN_ORDERS and disc_pct >= 10 and disc_pct > 2 * peers["discount_pct"]:
        flags.append(
            _flag(
                "medium",
                "Unusually high discounts",
                f"Discounts are {disc_pct}% of menu value (other hotels: {peers['discount_pct']}%). "
                "Commission is charged on the price after discount.",
            )
        )

    before, after = stats["previous_7_days"], stats["last_7_days"]
    if before >= MIN_ORDERS and after <= before * 0.5 and hotel.status == "active":
        flags.append(
            _flag(
                "medium",
                "Orders dropped sharply",
                f"{after} paid orders this week against {before} the week before while the hotel "
                "stayed open. Could be sales moving off the platform.",
            )
        )

    changes = list(
        (
            await session.execute(
                select(AuditLog)
                .where(AuditLog.target_type == "hotel", AuditLog.target_id == str(hotel.id))
                .order_by(AuditLog.created_at.desc())
                .limit(20)
            )
        ).scalars()
    )
    till_changes = [
        c for c in changes if c.created_at >= d30 and {"till_number", "till_name"} & set(c.details)
    ]
    if till_changes:
        flags.append(
            _flag(
                "medium",
                "Till changed recently",
                f"The M-Pesa Till was changed {len(till_changes)} time(s) in 30 days. "
                "Check it still belongs to the hotel.",
            )
        )

    bill = await billing.hotel_view(session, hotel, now)
    if bill["overdue"]:
        flags.append(
            _flag(
                "high",
                "Commission overdue",
                f"KES {bill['due_now']:,} was due {bill['due_date']} and is unpaid.",
            )
        )
    elif bill["paused_for_billing"]:
        flags.append(_flag("high", "Paused for unpaid commission", "Taking no orders until it pays."))

    flags.sort(key=lambda f: {"high": 0, "medium": 1, "info": 2}[f["level"]])

    return {
        "stats": stats,
        "peers": peers,
        "flags": flags,
        "location_check": acc,
        "billing": {
            "due_now": bill["due_now"],
            "due_date": bill["due_date"],
            "overdue": bill["overdue"],
            "unpaid_limit": bill["unpaid_limit"],
            "balance": bill["balance"],
            "pending_claims": bill["pending_claims"],
        },
        "recent_orders": [
            {
                "id": str(o.id),
                "code": o.code,
                "status": o.status,
                "type": o.type,
                "items_total": o.items_total,
                "order_discount": o.order_discount,
                "food_net": o.food_net,
                "commission": o.commission_amount,
                "created_at": o.created_at,
                "paid": o.paid_at is not None,
                "reason": o.reason,
            }
            for o in orders[:25]
        ],
        "changes": [
            {
                "at": c.created_at,
                "action": c.action,
                "what": sorted(c.details) if isinstance(c.details, dict) else [],
            }
            for c in changes
        ],
    }
