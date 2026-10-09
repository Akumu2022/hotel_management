"""Deliveries.

Ready -> Picked up -> On the way -> Delivered   (or Failed delivery, classified by the admin)

Dispatch: approved riders who are online claim open jobs (first tap wins: a conditional UPDATE),
and the super admin can assign or reassign any delivery until it is picked up.

Rider fee, as the spec's table:
  A + instant  hotel hands the fee over with the food; hotel and rider both confirm; the ledger
               entry is written once both have. A "not received" goes to the admin.
  A + weekly   on delivery: hotel owes the platform, platform owes the rider (weekly payout).
  B            on delivery the rider confirms "Fee received", or claims "Fee not paid":
               the customer is asked; "No" or no answer in 24 h -> platform compensates the rider
               (weekly payout, capped per week), the customer's number loses option B.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.time import utcnow
from app.models import (
    Customer,
    LedgerEntry,
    Order,
    OrderEvent,
    ReviewItem,
    RiderProfile,
    RiderStrike,
)
from app.payments import hook as payments_hook
from app.services import events, ledger, payments, push, riders, settings

CLAIMABLE = ("accepted", "preparing", "ready")
ON_JOB = ("accepted", "preparing", "ready", "picked_up", "on_the_way")
MAX_ACTIVE_JOBS = 2
MAX_CODE_ATTEMPTS = 5
FEE_ANSWER_WAIT = timedelta(hours=24)
STRIKE_WINDOW = timedelta(days=30)
FAULTS = ("customer_fault", "rider_fault", "hotel_fault")


async def _lock(session: AsyncSession, order_id: uuid.UUID) -> Order:
    order = (
        await session.execute(
            select(Order)
            .where(Order.id == order_id)
            .with_for_update()
            .execution_options(populate_existing=True)  # locked row, fresh values
        )
    ).scalar_one_or_none()
    if order is None or order.type != "delivery":
        raise AppError(404, "not_found", "Delivery not found")
    return order


def _wrong(order: Order, action: str) -> AppError:
    return AppError(
        409, "wrong_status", f"Can't {action}: the order is {order.status.replace('_', ' ')}"
    )


def _mine(order: Order, rider_id: uuid.UUID) -> None:
    if order.rider_id != rider_id:
        raise AppError(404, "not_found", "Delivery not found")
    if order.rider_seen_at is None:
        order.rider_seen_at = utcnow()  # acting on a job means it was seen


async def _move(session, order: Order, to: str, *, actor_type: str, actor_id, reason=None, **stamp):
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


def _event(session, order: Order, actor_type: str, actor_id, reason: str) -> None:
    """A note on the order's history without a status change."""
    session.add(
        OrderEvent(
            order_id=order.id,
            from_status=order.status,
            to_status=order.status,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
        )
    )
    events.order_changed(session, order)


# --- Dispatch ------------------------------------------------------------------------------------


async def set_online(session: AsyncSession, rider_id: uuid.UUID, online: bool, now: datetime):
    if not online:
        holding = await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(Order.rider_id == rider_id, Order.status.in_(ON_JOB))
        )
        if holding:
            raise AppError(409, "has_jobs", "Finish or drop your current job before going offline")
    p = (
        await riders.require_approved(session, rider_id)
        if online
        else await riders.profile(session, rider_id)
    )
    p.is_online = online
    p.last_seen_at = now
    await session.flush()
    return p


async def claim(
    session: AsyncSession, order_id: uuid.UUID, rider_id: uuid.UUID, now: datetime
) -> Order:
    p = await riders.require_approved(session, rider_id)
    if not p.is_online:
        raise AppError(409, "offline", "Go online to take jobs")
    active = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.rider_id == rider_id, Order.status.in_(ON_JOB))
    )
    if active >= MAX_ACTIVE_JOBS:
        raise AppError(
            409, "too_many_jobs", f"Finish your current jobs first (max {MAX_ACTIVE_JOBS})"
        )
    # First tap wins: only one UPDATE can see rider_id IS NULL.
    taken = await session.execute(
        update(Order)
        .where(
            Order.id == order_id,
            Order.type == "delivery",
            Order.rider_id.is_(None),
            Order.status.in_(CLAIMABLE),
        )
        .values(rider_id=rider_id, assigned_at=now, rider_seen_at=now)
        .returning(Order.id)
    )
    if taken.scalar_one_or_none() is None:
        order = await session.get(Order, order_id)
        if order is not None and order.rider_id == rider_id:
            return order  # repeat tap
        raise AppError(409, "job_taken", "Another rider took this job")
    order = await _lock(session, order_id)
    await session.refresh(order)
    _event(session, order, "rider", rider_id, "rider took the job")
    await session.flush()
    return order


async def assign(
    session: AsyncSession,
    order_id: uuid.UUID,
    rider_id: uuid.UUID,
    admin_id: uuid.UUID,
    now: datetime,
) -> Order:
    await riders.require_approved(session, rider_id)
    order = await _lock(session, order_id)
    if order.status not in CLAIMABLE:
        raise _wrong(order, "assign a rider")
    if order.rider_id == rider_id:
        return order
    previous = order.rider_id
    order.rider_id = rider_id
    order.assigned_at = now
    order.rider_seen_at = None  # rings the rider until they see it
    order.fee_hotel_confirmed_at = order.fee_rider_confirmed_at = None
    _event(session, order, "admin", admin_id, "rider reassigned" if previous else "rider assigned")
    push.notify(
        session,
        title=f"New job for you: #{order.code}",
        body="Open Chakula and tap Got it.",
        url="/rider",
        tag="rider-assigned",
        rider_id=rider_id,
    )
    await session.flush()
    return order


async def release(session: AsyncSession, order_id: uuid.UUID, rider_id: uuid.UUID) -> Order:
    order = await _lock(session, order_id)
    _mine(order, rider_id)
    if order.status not in CLAIMABLE:
        raise _wrong(order, "drop the job")
    order.rider_id = None
    order.assigned_at = None
    order.rider_seen_at = None
    _event(session, order, "rider", rider_id, "rider dropped the job")
    await session.flush()
    return order


async def seen(session: AsyncSession, order_id: uuid.UUID, rider_id: uuid.UUID) -> Order:
    """Rider tapped "Got it" on a job the admin gave them: their alarm stops."""
    order = await _lock(session, order_id)
    _mine(order, rider_id)
    await session.flush()
    events.order_changed(session, order)
    return order


# --- Rider fee: option A instant ---------------------------------------------------------------


async def _payout_mode(session, rider_id: uuid.UUID) -> str:
    return (await riders.profile(session, rider_id)).payout_mode


async def _instant_fee(session, order: Order) -> bool:
    return (
        order.rider_fee_mode == "included"
        and await _payout_mode(session, order.rider_id) == "instant"
    )


async def _maybe_record_instant(session, order: Order, actor_id) -> None:
    if order.fee_hotel_confirmed_at and order.fee_rider_confirmed_at:
        await ledger.record_rider_fee(
            session, order, rider_id=order.rider_id, payout_mode="instant", created_by=actor_id
        )


async def hotel_handover(
    session: AsyncSession,
    order_id: uuid.UUID,
    *,
    hotel_id: uuid.UUID,
    user_id: uuid.UUID,
    now: datetime,
) -> Order:
    """Hotel: "Handed to rider" (with the fee, for option A instant)."""
    order = await _lock(session, order_id)
    if order.hotel_id != hotel_id:
        raise AppError(404, "not_found", "Order not found")
    if order.rider_id is None:
        raise AppError(409, "no_rider", "No rider has taken this order yet")
    if order.status in ("picked_up", "on_the_way", "delivered") and order.fee_hotel_confirmed_at:
        return order
    if order.status == "ready":
        await _move(
            session, order, "picked_up", actor_type="staff", actor_id=user_id, picked_up_at=now
        )
    elif order.status not in ("picked_up", "on_the_way", "delivered"):
        raise _wrong(order, "hand over")
    if await _instant_fee(session, order) and order.fee_hotel_confirmed_at is None:
        order.fee_hotel_confirmed_at = now
        await _maybe_record_instant(session, order, user_id)
    await session.flush()
    return order


async def rider_picked_up(
    session: AsyncSession,
    order_id: uuid.UUID,
    rider_id: uuid.UUID,
    *,
    fee_received: bool | None,
    now: datetime,
) -> Order:
    """Rider: "Picked up". For option A instant, also whether the fee came with the food."""
    order = await _lock(session, order_id)
    _mine(order, rider_id)
    if order.status == "ready":
        await _move(
            session, order, "picked_up", actor_type="rider", actor_id=rider_id, picked_up_at=now
        )
    elif order.status not in ("picked_up", "on_the_way", "delivered"):
        raise _wrong(order, "pick up")
    if (
        await _instant_fee(session, order)
        and order.fee_rider_confirmed_at is None
        and fee_received is not None
    ):
        if fee_received:
            order.fee_rider_confirmed_at = now
            await _maybe_record_instant(session, order, rider_id)
        else:
            await payments.open_review(
                session,
                type="fee_dispute",
                hotel_id=order.hotel_id,
                order_id=order.id,
                reason=f"Rider says the hotel didn't hand over the KES {order.rider_fee} fee",
            )
    await session.flush()
    return order


async def on_the_way(
    session: AsyncSession, order_id: uuid.UUID, rider_id: uuid.UUID, now: datetime
) -> Order:
    order = await _lock(session, order_id)
    _mine(order, rider_id)
    if order.status == "on_the_way":
        return order
    if order.status != "picked_up":
        raise _wrong(order, "start the trip")
    return await _move(
        session, order, "on_the_way", actor_type="rider", actor_id=rider_id, on_the_way_at=now
    )


# --- Delivered -----------------------------------------------------------------------------------


async def delivered(
    session: AsyncSession,
    order_id: uuid.UUID,
    rider_id: uuid.UUID,
    *,
    code: str,
    cash_fee_received: bool | None,
    now: datetime,
) -> Order:
    """The customer's 4-digit code proves the rider met them. Five wrong tries lock it."""
    order = await _lock(session, order_id)
    _mine(order, rider_id)
    if order.status == "delivered":
        return order
    if order.status not in ("picked_up", "on_the_way"):
        raise _wrong(order, "deliver")
    if order.delivery_code_attempts >= MAX_CODE_ATTEMPTS:
        raise AppError(423, "code_locked", "Too many wrong codes. Call the duty person.")
    if code.strip() != order.delivery_code:
        order.delivery_code_attempts += 1
        left = MAX_CODE_ATTEMPTS - order.delivery_code_attempts
        if left == 0:
            await payments.open_review(
                session,
                type="failed_delivery",
                hotel_id=order.hotel_id,
                order_id=order.id,
                reason="Five wrong delivery codes: call the rider and the customer",
            )
        await session.flush()
        # Committed by the route even though this is an error, so the count sticks.
        raise AppError(
            422, "wrong_code", f"Wrong code. {left} tries left." if left else "Wrong code. Locked."
        )
    await _move(
        session,
        order,
        "delivered",
        actor_type="rider",
        actor_id=rider_id,
        delivered_at=now,
        closed_at=now,
    )
    customer = await session.get(Customer, order.customer_phone, with_for_update=True)
    if customer is not None:
        customer.completed_orders += 1  # counts toward the stamp card and trust
    if order.rider_fee_mode == "included" and await _payout_mode(session, rider_id) == "weekly":
        await ledger.record_rider_fee(
            session, order, rider_id=rider_id, payout_mode="weekly", created_by=rider_id
        )
    elif order.rider_fee_mode == "cash" and cash_fee_received:
        await ledger.record_rider_fee(
            session, order, rider_id=rider_id, payout_mode="instant", created_by=rider_id
        )
    await payments_hook.on_delivered(session, order)  # no-op unless PAYMENTS_ENABLED
    await session.flush()
    return order


async def cash_fee_received(
    session: AsyncSession, order_id: uuid.UUID, rider_id: uuid.UUID
) -> Order:
    order = await _lock(session, order_id)
    _mine(order, rider_id)
    if order.rider_fee_mode != "cash" or order.status != "delivered" or order.fee_not_paid_at:
        raise _wrong(order, "confirm the cash fee")
    await ledger.record_rider_fee(
        session, order, rider_id=rider_id, payout_mode="instant", created_by=rider_id
    )
    return order


# --- option B fee not paid ----------------------------------------------------------------


async def fee_not_paid(
    session: AsyncSession, order_id: uuid.UUID, rider_id: uuid.UUID, now: datetime
) -> Order:
    """Only after a verified delivery (the rider met the customer)."""
    order = await _lock(session, order_id)
    _mine(order, rider_id)
    if order.rider_fee_mode != "cash" or order.status != "delivered":
        raise _wrong(order, "report the fee unpaid")
    if order.fee_not_paid_at:
        return order
    paid = await session.scalar(
        select(func.count())
        .select_from(LedgerEntry)
        .where(LedgerEntry.order_id == order.id, LedgerEntry.entry_type == "rider_fee_cash")
    )
    if paid:
        raise AppError(409, "fee_confirmed", "You already confirmed this fee as received")
    order.fee_not_paid_at = now
    _event(session, order, "rider", rider_id, "rider says the delivery fee wasn't paid")
    await session.flush()
    return order


async def customer_answer(session: AsyncSession, order: Order, answer: str, now: datetime) -> Order:
    """Tracking page: "Did you pay the rider KES X?" """
    order = await _lock(session, order.id)
    if order.fee_not_paid_at is None or order.customer_fee_answer is not None:
        return order
    order.customer_fee_answer = answer
    if answer == "yes":
        await payments.open_review(
            session,
            type="fee_dispute",
            hotel_id=order.hotel_id,
            order_id=order.id,
            reason=f"Rider says the KES {order.rider_fee} fee wasn't paid; customer says it was",
        )
    else:
        await compensate(session, order, None, now)
    _event(session, order, "customer", None, f"customer answered '{answer}' about the delivery fee")
    await session.flush()
    return order


async def compensate(session: AsyncSession, order: Order, admin_id, now: datetime) -> bool:
    """Platform pays the rider (weekly payout); the customer's number loses option B, then is
    blocklisted on a second case. Above the weekly cap it waits for the admin instead."""
    if admin_id is None:
        values, _ = await settings.load(session)
        week = await session.scalar(
            select(func.count())
            .select_from(LedgerEntry)
            .where(
                LedgerEntry.entry_type == "rider_compensation",
                LedgerEntry.to_id == order.rider_id,
                LedgerEntry.created_at >= now - timedelta(days=7),
            )
        )
        if week >= values.rider_compensation_weekly_cap:
            await payments.open_review(
                session,
                type="fee_dispute",
                hotel_id=order.hotel_id,
                order_id=order.id,
                reason="Unpaid delivery fee: this rider is over the weekly compensation limit",
            )
            return False
    await ledger.record_rider_compensation(
        session, order, rider_id=order.rider_id, created_by=admin_id
    )
    await _penalize_customer(session, order.customer_phone)
    return True


async def _penalize_customer(session, phone: str) -> None:
    customer = await session.get(Customer, phone, with_for_update=True)
    if customer is None:
        return
    if customer.option_b_blocked:
        customer.blocklisted = True
    customer.option_b_blocked = True


async def answer_timeouts(session: AsyncSession, now: datetime) -> int:
    """Job: no answer from the customer within 24 h counts as "No"."""
    stale = (
        (
            await session.execute(
                select(Order).where(
                    Order.fee_not_paid_at.is_not(None),
                    Order.fee_not_paid_at < now - FEE_ANSWER_WAIT,
                    Order.customer_fee_answer.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for order in stale:
        await customer_answer(session, order, "no", now)
    return len(stale)


# --- failed delivery -----------------------------------------------------------------------


async def report_failed(
    session: AsyncSession, order_id: uuid.UUID, rider_id: uuid.UUID, reason: str, now: datetime
) -> Order:
    order = await _lock(session, order_id)
    _mine(order, rider_id)
    if order.status == "failed_delivery":
        return order
    if order.status not in ("picked_up", "on_the_way"):
        raise _wrong(order, "report a failed delivery")
    await _move(
        session,
        order,
        "failed_delivery",
        actor_type="rider",
        actor_id=rider_id,
        reason=reason,
        closed_at=now,
    )
    order.reason = f"Delivery failed: {reason}"
    await payments.open_review(
        session,
        type="failed_delivery",
        hotel_id=order.hotel_id,
        order_id=order.id,
        reason=f"Rider reports: {reason}",
    )
    await session.flush()
    return order


async def admin_close(
    session: AsyncSession,
    order_id: uuid.UUID,
    outcome: str,
    reason: str,
    admin_id: uuid.UUID,
    now: datetime,
    *,
    rider_paid_cash: bool | None = None,
) -> Order:
    """The way out of a delivery nobody is finishing (rider's phone died, rider vanished, the
    customer confirms they got the food by phone). Only once the food has left the hotel.

    "delivered" follows the rider's own delivery rules without the code. "failed" files the same
    review item a rider's failed delivery does, so the admin then decides whose fault it was
    and refunds, pay and strikes follow the existing rules."""
    order = await _lock(session, order_id)
    if order.status in ("delivered", "failed_delivery"):
        return order  # a double tap changes nothing
    if order.status not in ("picked_up", "on_the_way"):
        raise _wrong(order, "close")
    if outcome == "failed":
        await _move(
            session,
            order,
            "failed_delivery",
            actor_type="admin",
            actor_id=admin_id,
            reason=reason,
            closed_at=now,
        )
        order.reason = f"Delivery failed: {reason}"
        await payments.open_review(
            session,
            type="failed_delivery",
            hotel_id=order.hotel_id,
            order_id=order.id,
            reason=f"Closed by admin: {reason}",
        )
    elif outcome == "delivered":
        cash = order.rider_fee_mode == "cash"
        if cash and rider_paid_cash is None:
            raise AppError(
                422, "rider_paid_cash_required", "Say whether the customer paid the rider's fee"
            )
        await _move(
            session,
            order,
            "delivered",
            actor_type="admin",
            actor_id=admin_id,
            reason=reason,
            delivered_at=now,
            closed_at=now,
        )
        customer = await session.get(Customer, order.customer_phone, with_for_update=True)
        if customer is not None:
            customer.completed_orders += 1
        rider_id = order.rider_id
        if order.rider_fee_mode == "included" and await _payout_mode(session, rider_id) == "weekly":
            await ledger.record_rider_fee(
                session, order, rider_id=rider_id, payout_mode="weekly", created_by=admin_id
            )
        elif cash and rider_paid_cash:
            await ledger.record_rider_fee(
                session, order, rider_id=rider_id, payout_mode="instant", created_by=admin_id
            )
        elif cash:  # the customer did not pay the rider at the door: the platform does
            await ledger.record_rider_compensation(
                session, order, rider_id=rider_id, created_by=admin_id
            )
    else:
        raise AppError(422, "bad_action", "Choose delivered or failed")
    await session.flush()
    return order


async def classify_failure(
    session: AsyncSession, item: ReviewItem, fault: str, admin_id: uuid.UUID, now: datetime
) -> None:
    """The super admin decides whose fault a failed delivery was."""
    order = await _lock(session, item.order_id)
    if order.status != "failed_delivery":
        raise _wrong(order, "classify")
    rider_paid_cash = order.rider_fee_mode == "cash"
    if fault == "customer_fault":
        await _pay_rider_anyway(session, order, admin_id, rider_paid_cash, now)
        await _penalize_customer(session, order.customer_phone)
    elif fault == "hotel_fault":
        await ledger.refund_rest(
            session, order, reason="Failed delivery: hotel fault", approved_by=admin_id
        )
        await _pay_rider_anyway(session, order, admin_id, rider_paid_cash, now)
    elif fault == "rider_fault":
        refund = await ledger.refund_rest(
            session, order, reason="Failed delivery: rider fault", approved_by=admin_id
        )
        if refund is not None:
            await ledger.credit_failed_delivery(
                session, order, amount=refund.amount, created_by=admin_id
            )
        session.add(
            RiderStrike(
                rider_id=order.rider_id, order_id=order.id, reason=item.reason, created_by=admin_id
            )
        )
        await session.flush()
        strikes = await session.scalar(
            select(func.count())
            .select_from(RiderStrike)
            .where(
                RiderStrike.rider_id == order.rider_id,
                RiderStrike.created_at >= now - STRIKE_WINDOW,
            )
        )
        if strikes >= 2:
            p = await session.get(RiderProfile, order.rider_id)
            if p.kyc_status == "approved":
                await riders.review(
                    session,
                    order.rider_id,
                    "suspend",
                    "Two failed deliveries in 30 days",
                    admin_id,
                    now,
                )
    else:
        raise AppError(422, "bad_action", f"Choose one of: {', '.join(FAULTS)}")
    _event(session, order, "admin", admin_id, f"failed delivery: {fault.replace('_', ' ')}")


async def _pay_rider_anyway(
    session, order: Order, admin_id, cash_mode: bool, now: datetime
) -> None:
    """The rider did the trip: option A as their payout setting; option B from the platform."""
    if cash_mode:
        await ledger.record_rider_compensation(
            session, order, rider_id=order.rider_id, created_by=admin_id
        )
    else:
        mode = await _payout_mode(session, order.rider_id)
        if mode == "instant" and not (
            order.fee_hotel_confirmed_at and order.fee_rider_confirmed_at
        ):
            mode = "weekly"  # never handed over at pickup: settle through the statements
        await ledger.record_rider_fee(
            session, order, rider_id=order.rider_id, payout_mode=mode, created_by=admin_id
        )


async def resolve_fee_dispute(
    session: AsyncSession, item: ReviewItem, action: str, admin_id: uuid.UUID, now: datetime
) -> None:
    order = await _lock(session, item.order_id)
    if action == "pay_rider":
        if order.rider_fee_mode == "cash":
            await compensate(session, order, admin_id, now)
        else:  # option A: the hotel didn't hand it over; settle via statements
            await ledger.record_rider_fee(
                session, order, rider_id=order.rider_id, payout_mode="weekly", created_by=admin_id
            )
    elif action != "no_payment":
        raise AppError(422, "bad_action", "Choose pay_rider or no_payment")
    _event(session, order, "admin", admin_id, f"fee dispute: {action.replace('_', ' ')}")
