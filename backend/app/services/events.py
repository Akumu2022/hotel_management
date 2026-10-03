"""Live updates (spec section 4: SSE per hotel, per order, per rider; in-memory broker for the
single API process at launch).

Services call `emit(session, channel, payload)` inside their transaction. The events are sent
only after that transaction COMMITS (and dropped on rollback), so a screen never refetches
before the change is visible. Moving to several API processes means swapping this broker for
PostgreSQL LISTEN/NOTIFY; callers do not change.

Channels: "hotel:<id>", "order:<tracking token>", "admin".
"""

import asyncio
import json
import logging
from collections import defaultdict
from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

log = logging.getLogger("app.events")

_subscribers: dict[str, set[asyncio.Queue]] = defaultdict(set)
_KEY = "pending_events"
HEARTBEAT_S = 15


def emit(session: AsyncSession | Session, channel: str, payload: dict) -> None:
    sync = session.sync_session if isinstance(session, AsyncSession) else session
    sync.info.setdefault(_KEY, []).append((channel, payload))


def publish(channel: str, payload: dict) -> None:
    for q in list(_subscribers.get(channel, ())):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:  # a stuck client: drop rather than block everyone
            log.warning("dropping event for slow subscriber on %s", channel)


@event.listens_for(Session, "after_commit")
def _after_commit(sync_session: Session) -> None:
    for channel, payload in sync_session.info.pop(_KEY, []):
        publish(channel, payload)


@event.listens_for(Session, "after_soft_rollback")
def _after_rollback(sync_session: Session, _previous) -> None:
    sync_session.info.pop(_KEY, None)


def subscriber_count(channel: str) -> int:
    return len(_subscribers.get(channel, ()))


async def stream(channel: str) -> AsyncIterator[str]:
    """Server-Sent Events for one channel, with a heartbeat so proxies keep it open."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _subscribers[channel].add(q)
    try:
        yield ": connected\n\n"
        while True:
            try:
                payload = await asyncio.wait_for(q.get(), timeout=HEARTBEAT_S)
                yield f"data: {json.dumps(payload, default=str)}\n\n"
            except TimeoutError:
                yield ": ping\n\n"
    finally:
        _subscribers[channel].discard(q)
        if not _subscribers[channel]:
            _subscribers.pop(channel, None)


def order_changed(session, order, extra: dict | None = None) -> None:
    """Tell the hotel's screen, the customer's tracking page and the admin board."""
    payload = {
        "type": "order",
        "order_id": str(order.id),
        "code": order.code,
        "status": order.status,
        **(extra or {}),
    }
    emit(session, f"hotel:{order.hotel_id}", payload)
    emit(session, f"order:{order.tracking_token}", payload)
    emit(session, "admin", payload)
    if order.type == "delivery":
        # Riders' job lists refresh on this; no customer details go to the riders channel.
        emit(
            session,
            "riders",
            {
                "type": "job",
                "order_id": str(order.id),
                "status": order.status,
                "rider_id": str(order.rider_id) if order.rider_id else None,
            },
        )
