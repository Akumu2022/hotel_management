"""Web Push: the alarms that still reach staff and riders when Chakula is closed.

The page rings by itself while it is open (web/src/lib/alarm.ts). This covers the rest: a push
message wakes the phone or browser, shows a notification that stays up until it is opened, and
the page takes over from there. Nothing here changes the rules for what needs doing.

Off until VAPID keys are configured (`python -m app.cli vapid-keys`). Messages are queued with
`notify()` inside the same transaction as the change, so they go out only if it commits.
"""

import asyncio
import json
import logging
import uuid

from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.db import SessionLocal
from app.models import PushSubscription, RiderProfile, User
from app.services import events

log = logging.getLogger("app.push")

CHANNEL = "push"  # an events channel that is delivered here instead of to a screen
TTL_S = 3600  # an alarm older than an hour is no use
_tasks: set[asyncio.Task] = set()


def enabled() -> bool:
    cfg = get_config()
    return bool(cfg.vapid_private_key and cfg.vapid_public_key)


def notify(
    session: AsyncSession,
    *,
    title: str,
    body: str,
    url: str,
    tag: str,
    hotel_id: uuid.UUID | None = None,
    admins: bool = False,
    rider_id: uuid.UUID | None = None,
    online_riders: bool = False,
) -> None:
    """Queue one message for whoever is in the audience; sent after the transaction commits.
    The same `tag` replaces an earlier notification instead of stacking."""
    if not enabled():
        return
    audience = {
        "hotel_id": str(hotel_id) if hotel_id else None,
        "admins": admins,
        "rider_id": str(rider_id) if rider_id else None,
        "online_riders": online_riders,
    }
    events.emit(
        session,
        CHANNEL,
        {"title": title, "body": body[:140], "url": url, "tag": tag, "audience": audience},
    )


def schedule(payload: dict) -> None:
    """Called by the events broker after a commit. Never blocks, never raises."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(deliver(payload))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _recipients(session: AsyncSession, audience: dict) -> list[uuid.UUID]:
    ids: set[uuid.UUID] = set()
    if audience.get("hotel_id"):
        rows = await session.scalars(
            select(User.id).where(
                User.hotel_id == uuid.UUID(audience["hotel_id"]),
                User.is_active.is_(True),
                User.role.in_(("hotel_admin", "cashier")),
            )
        )
        ids.update(rows)
    if audience.get("admins"):
        rows = await session.scalars(
            select(User.id).where(User.role == "super_admin", User.is_active.is_(True))
        )
        ids.update(rows)
    if audience.get("rider_id"):
        ids.add(uuid.UUID(audience["rider_id"]))
    if audience.get("online_riders"):
        rows = await session.scalars(
            select(RiderProfile.user_id)
            .join(User, User.id == RiderProfile.user_id)
            .where(
                RiderProfile.kyc_status == "approved",
                RiderProfile.is_online.is_(True),
                User.is_active.is_(True),
            )
        )
        ids.update(rows)
    return list(ids)


def _send(endpoint: str, keys: dict, data: str) -> None:
    cfg = get_config()
    webpush(
        subscription_info={"endpoint": endpoint, "keys": keys},
        data=data,
        vapid_private_key=cfg.vapid_private_key,
        vapid_claims={"sub": cfg.vapid_subject},
        ttl=TTL_S,
        headers={"Urgency": "high"},
    )


async def _send_one(sub: PushSubscription, data: str) -> uuid.UUID | None:
    """The subscription's id when it is gone for good (the user removed it), else None."""
    try:
        await asyncio.to_thread(_send, sub.endpoint, sub.keys, data)
    except WebPushException as e:
        status = getattr(e.response, "status_code", None)
        if status in (404, 410):
            return sub.id
        log.warning("push failed (%s): %s", status, e)
    except Exception:
        log.warning("push failed", exc_info=True)
    return None


async def deliver(payload: dict) -> int:
    """Send one queued message to every subscription in its audience. Returns how many went."""
    data = json.dumps({k: payload[k] for k in ("title", "body", "url", "tag")})
    try:
        async with SessionLocal() as session:
            users = await _recipients(session, payload["audience"])
            if not users:
                return 0
            subs = (
                await session.scalars(
                    select(PushSubscription).where(PushSubscription.user_id.in_(users))
                )
            ).all()
            gone = await asyncio.gather(*(_send_one(s, data) for s in subs))
            dead = [g for g in gone if g]
            if dead:
                await session.execute(delete(PushSubscription).where(PushSubscription.id.in_(dead)))
                await session.commit()
            return len(subs) - len(dead)
    except Exception:
        log.exception("push delivery failed")
        return 0
