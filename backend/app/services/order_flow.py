"""Hotel-side order status flow (spec section 9, DECISIONS D6, D12c).

Pickup:   Paid -> Accepted -> Preparing -> Ready -> Collected
Delivery: Paid -> Accepted -> Preparing -> Ready -> (rider, M6)
Cash pickup starts in Awaiting payment and is accepted directly (after a confirmation call for
first-time numbers); cash is recorded at collection if not before.

Each step runs under a row lock and only from its expected previous status. Repeating the same
step returns the current state (a double tap on bad network makes one change); any other jump
is a 409.
"""

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Customer, Hotel, Order, OrderEvent
from app.services import events, ledger, payments, settings

REJECT_REASONS = {
    "sold_out": "An item is sold out",
    "too_busy": "The kitchen is too busy right now",
    "closing": "The hotel is closing",
    "cannot_deliver": "We can't deliver to that place",
    "other": "The hotel couldn't take this order",
    "not_accepted_in_time": "The hotel didn't respond in time",
}
ACTIVE = ("paid", "accepted", "preparing", "ready")
log = logging.getLogger("app.orders")


def _accept_from(order: Order) -> tuple[str, ...]:
    return ("paid", "awaiting_payment") if order.payment_method == "cash" else ("paid",)


async def _lock(session: AsyncSession, order_id: uuid.UUID, hotel_id: uuid.UUID | None) -> Order:
    stmt = select(Order).where(Order.id == order_id).with_for_update()
    if hotel_id is not None:
        stmt = stmt.where(Order.hotel_id == hotel_id)  # hotel scoping: other hotels get 404
    order = (await session.execute(stmt)).scalar_one_or_none()
    if order is None:
        raise AppError(404, "not_found", "Order not found")
    return order


def _wrong_state(order: Order, action: str) -> AppError:
    return AppError(
        409, "wrong_status", f"Can't {action} an order that is {order.status.replace('_', ' ')}"
    )


async def _move(
    session,
    order: Order,
    to: str,
    *,
    actor_type: str,
    actor_id,
    now: datetime,
    reason=None,
    **stamp,
) -> Order:
    previous = order.status
    order.status = to
    for k, v in stamp.items():
        setattr(order, k, v)
    session.add(
        OrderEvent(
            order_id=order.id,
            from_status=previous,
            to_status=to,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
        )
    )
    await session.flush()
    events.order_changed(session, order)
    return order


async def accept(session, order_id, *, prep_minutes: int, user_id, hotel_id, now) -> Order:
    if not 1 <= prep_minutes <= 180:
        raise AppError(422, "bad_prep", "Prep time must be 1 to 180 minutes")
    order = await _lock(session, order_id, hotel_id)
    if order.status == "accepted":
        return order
    if order.status not in _accept_from(order):
        raise _wrong_state(order, "accept")
    return await _move(
        session,
        order,
        "accepted",
        actor_type="staff",
        actor_id=user_id,
        now=now,
        accepted_at=now,
        prep_minutes=prep_minutes,
    )


async def preparing(session, order_id, *, user_id, hotel_id, now) -> Order:
    order = await _lock(session, order_id, hotel_id)
    if order.status == "preparing":
        return order
    if order.status != "accepted":
        raise _wrong_state(order, "start preparing")
    return await _move(
        session, order, "preparing", actor_type="staff", actor_id=user_id, now=now, preparing_at=now
    )


async def ready(session, order_id, *, user_id, hotel_id, now) -> Order:
    order = await _lock(session, order_id, hotel_id)
    if order.status == "ready":
        return order
    if order.status != "preparing":
        raise _wrong_state(order, "mark ready")
    return await _move(
        session, order, "ready", actor_type="staff", actor_id=user_id, now=now, ready_at=now
    )


async def collected(session, order_id, *, user_id, hotel_id, now) -> Order:
    order = await _lock(session, order_id, hotel_id)
    if order.status == "collected":
        return order
    if order.type == "delivery":
        raise AppError(409, "not_pickup", "Delivery orders are handed to a rider, not collected")
    if order.status != "ready":
        raise _wrong_state(order, "hand over")
    if order.payment_method == "cash" and order.paid_at is None:
        await payments.cash_received(session, order.id, user_id, now)  # cash recorded at collection
    await _count_completed(session, order, now)
    return await _move(
        session,
        order,
        "collected",
        actor_type="staff",
        actor_id=user_id,
        now=now,
        collected_at=now,
        closed_at=now,
    )


async def _count_completed(session, order: Order, now: datetime) -> None:
    customer = await session.get(Customer, order.customer_phone)
    if customer is not None:
        customer.completed_orders += 1
        customer.last_order_at = now


async def reject(
    session,
    order_id,
    *,
    reason_code: str,
    note: str | None,
    user_id,
    hotel_id,
    now,
    actor_type: str = "staff",
) -> Order:
    """Reject before preparing. Money already received becomes a full refund record (spec 9)."""
    if reason_code not in REJECT_REASONS:
        raise AppError(422, "bad_reason", "Choose a reason")
    order = await _lock(session, order_id, hotel_id)
    if order.status == "rejected":
        return order
    if order.status not in ("paid", "accepted", *(_accept_from(order))):
        raise _wrong_state(order, "reject")
    reason = REJECT_REASONS[reason_code] + (f": {note}" if note else "")
    await ledger.refund_rest(
        session,
        order,
        reason=f"Rejected: {reason}",
        approved_by=user_id,
        refund_id=uuid.uuid5(order.id, "reject-refund"),
    )
    order.reason = reason  # shown to the customer on the tracking page
    return await _move(
        session,
        order,
        "rejected",
        actor_type=actor_type,
        actor_id=user_id,
        now=now,
        reason=reason,
        closed_at=now,
    )


CANCEL_REASONS = {
    "ran_out": "The hotel ran out of an item",
    "kitchen_problem": "A problem in the kitchen",
    "customer_asked": "Cancelled at the customer's request",
    "other": "The order had to be cancelled",
}
CANCELLABLE_AFTER_ACCEPT = ("accepted", "preparing", "ready")


async def cancel_after_accept(
    session,
    order_id,
    *,
    reason_code: str,
    note: str | None,
    user_id,
    hotel_id,
    now,
    actor_type: str = "staff",
) -> Order:
    """The hotel can't finish an order it accepted (D24). Hotel admin (own hotel) or super admin.
    Everything received is refunded; a rider who took the job loses it from their list. Once the
    food is with a rider, the failed-delivery flow applies instead."""
    if reason_code not in CANCEL_REASONS:
        raise AppError(422, "bad_reason", "Choose a reason")
    order = await _lock(session, order_id, hotel_id)
    if order.status == "cancelled":
        return order  # repeat tap
    if order.status not in CANCELLABLE_AFTER_ACCEPT:
        if order.status in ("picked_up", "on_the_way"):
            raise AppError(
                409, "with_rider", "The rider has the food: report a failed delivery instead"
            )
        raise _wrong_state(order, "cancel")
    by = "Chakula" if actor_type == "admin" else "the hotel"
    reason = f"{CANCEL_REASONS[reason_code]}{f': {note}' if note else ''} (cancelled by {by})"
    await ledger.refund_rest(
        session,
        order,
        reason=f"Cancelled after acceptance: {reason}",
        approved_by=user_id,
        refund_id=uuid.uuid5(order.id, "cancel-refund"),
    )
    order.reason = reason
    return await _move(
        session,
        order,
        "cancelled",
        actor_type=actor_type,
        actor_id=user_id,
        now=now,
        reason=reason,
        closed_at=now,
    )


# --- D6: acceptance timeout ---------------------------------------------------------------------


def waiting_since(order: Order) -> datetime:
    """When the hotel's clock to accept started: payment for M-Pesa, placement for cash."""
    return order.paid_at or order.created_at


async def unaccepted(session, hotel_id: uuid.UUID | None = None) -> list[Order]:
    stmt = select(Order).where(
        (Order.status == "paid")
        | ((Order.status == "awaiting_payment") & (Order.payment_method == "cash"))
    )
    if hotel_id:
        stmt = stmt.where(Order.hotel_id == hotel_id)
    return list((await session.execute(stmt.order_by(Order.created_at))).scalars().all())


async def auto_reject_late(session: AsyncSession, now: datetime) -> int:
    """10 minutes without Accept: reject with reason not_accepted_in_time (refund recorded).
    Two auto-rejects in a row at a hotel switch its "Accepting orders" off (D6)."""
    values, _ = await settings.load(session)
    limit = timedelta(minutes=values.acceptance_timeout_minutes)
    done = 0
    for o in await unaccepted(session):
        if waiting_since(o) > now - limit:
            continue
        try:
            async with session.begin_nested():  # one bad order must not block the others
                await reject(
                    session,
                    o.id,
                    reason_code="not_accepted_in_time",
                    note=None,
                    user_id=None,
                    hotel_id=None,
                    now=now,
                    actor_type="system",
                )
        except AppError:
            log.exception("auto-reject failed for order %s", o.code)
            continue
        done += 1
        if await _two_misses_in_a_row(session, o.hotel_id):
            hotel = await session.get(Hotel, o.hotel_id, with_for_update=True)
            if hotel.accepting_orders:
                hotel.accepting_orders = False
                events.emit(
                    session, f"hotel:{hotel.id}", {"type": "hotel", "accepting_orders": False}
                )
                events.emit(session, "admin", {"type": "hotel_paused", "hotel": hotel.name})
    return done


async def _two_misses_in_a_row(session, hotel_id) -> bool:
    """Were the hotel's last two orders that left 'waiting for acceptance' both timed out?"""
    rows = (
        (
            await session.execute(
                select(OrderEvent.reason)
                .join(Order, Order.id == OrderEvent.order_id)
                .where(
                    Order.hotel_id == hotel_id,
                    OrderEvent.from_status.in_(("paid", "awaiting_payment")),
                    OrderEvent.to_status.in_(("accepted", "rejected")),
                )
                .order_by(OrderEvent.created_at.desc())
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    timed_out = REJECT_REASONS["not_accepted_in_time"]
    return len(rows) == 2 and all(r == timed_out for r in rows)


async def duty_alerts(session, now: datetime) -> list[dict]:
    """Orders waiting longer than the duty-alert time (D6: 5 minutes), for the admin board."""
    values, _ = await settings.load(session)
    alert = timedelta(minutes=values.acceptance_alert_minutes)
    out = []
    for o in await unaccepted(session):
        waited = now - waiting_since(o)
        if waited >= alert:
            hotel = await session.get(Hotel, o.hotel_id)
            out.append(
                {
                    "order_id": str(o.id),
                    "code": o.code,
                    "hotel": hotel.name,
                    "hotel_phone": hotel.phone,
                    "minutes": int(waited.total_seconds() // 60),
                    "auto_reject_in": max(
                        0, values.acceptance_timeout_minutes - int(waited.total_seconds() // 60)
                    ),
                }
            )
    return out


async def misses_count(session, hotel_id, since: datetime) -> int:
    return (
        await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.hotel_id == hotel_id,
                Order.reason == REJECT_REASONS["not_accepted_in_time"],
                Order.closed_at >= since,
            )
        )
        or 0
    )
