"""Rider live location.

The rider's phone sends a GPS fix about every 30 seconds while the rider is online, and only
then: going offline stops tracking. The latest fix shows on the admin's Dispatch map next to
the hotel and the customer; during a job each fix is also kept (at most one per 20 s) as the
job's trail, for disputes. Trails are deleted after 30 days.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select

from app.core.errors import AppError
from app.models import Order, RiderPing, RiderProfile
from app.services import events
from app.services.delivery import ON_JOB

PING_EVERY = timedelta(seconds=20)
KEEP_PINGS = timedelta(days=30)
STALE_AFTER = timedelta(minutes=5)  # older fixes show as "last seen", not live
MAX_ACCURACY_M = 100


async def record(
    session, rider_id: uuid.UUID, *, lat: float, lng: float, accuracy_m: int | None, now: datetime
) -> RiderProfile:
    p = await session.get(RiderProfile, rider_id, with_for_update=True)
    if p is None or p.kyc_status != "approved":
        raise AppError(403, "not_approved", "Only approved riders share their location")
    if not p.is_online:
        raise AppError(409, "offline", "Location is only shared while you're online")
    # A rough fix (weak GPS, Wi-Fi guess) would make the rider jump on the map. Keep the
    # last good one while it is fresh; with nothing better, a rough fix still beats none.
    rough = accuracy_m is not None and accuracy_m > MAX_ACCURACY_M
    fresh = p.last_location_at is not None and now - p.last_location_at < STALE_AFTER
    good_before = p.last_accuracy_m is not None and p.last_accuracy_m <= MAX_ACCURACY_M
    if rough and fresh and good_before:
        p.last_seen_at = now
        return p
    p.last_lat, p.last_lng = round(lat, 6), round(lng, 6)
    p.last_accuracy_m = min(accuracy_m, 30_000) if accuracy_m is not None else None
    p.last_location_at = now
    p.last_seen_at = now

    jobs = (
        (
            await session.execute(
                select(Order).where(Order.rider_id == rider_id, Order.status.in_(ON_JOB))
            )
        )
        .scalars()
        .all()
    )
    last_ping = (
        await session.scalar(select(func.max(RiderPing.at)).where(RiderPing.rider_id == rider_id))
        if jobs
        else None
    )
    if jobs and (last_ping is None or now - last_ping >= PING_EVERY):
        # The job on the road first: that's the one a dispute would be about.
        job = sorted(jobs, key=lambda o: o.status not in ("picked_up", "on_the_way"))[0]
        session.add(
            RiderPing(
                rider_id=rider_id,
                order_id=job.id,
                lat=p.last_lat,
                lng=p.last_lng,
                accuracy_m=p.last_accuracy_m,
                at=now,
            )
        )
    await session.flush()
    events.emit(
        session,
        "admin",
        {
            "type": "rider_location",
            "rider_id": str(rider_id),
            "lat": p.last_lat,
            "lng": p.last_lng,
            "at": now.isoformat(),
        },
    )
    # The customer whose food this rider is carrying watches the same fix (live map).
    for o in jobs:
        if o.status in ("picked_up", "on_the_way"):
            events.emit(
                session,
                f"order:{o.tracking_token}",
                {
                    "type": "rider_location",
                    "lat": p.last_lat,
                    "lng": p.last_lng,
                    "at": now.isoformat(),
                },
            )
    return p


def is_live(p: RiderProfile, now: datetime) -> bool:
    return bool(p.is_online and p.last_location_at and now - p.last_location_at < STALE_AFTER)


async def trail(session, order_id: uuid.UUID) -> list[dict]:
    rows = (
        (
            await session.execute(
                select(RiderPing).where(RiderPing.order_id == order_id).order_by(RiderPing.at)
            )
        )
        .scalars()
        .all()
    )
    return [{"lat": r.lat, "lng": r.lng, "accuracy_m": r.accuracy_m, "at": r.at} for r in rows]


async def prune(session, now: datetime) -> int:
    """Background job."""
    result = await session.execute(delete(RiderPing).where(RiderPing.at < now - KEEP_PINGS))
    return result.rowcount or 0
