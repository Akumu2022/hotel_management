"""The only code the pilot calls: one additive call after delivery is confirmed. It does nothing
while PAYMENTS_ENABLED is off. A failure here propagates, so the delivery rolls back and the
rider simply enters the code again (credited exactly once, by idempotency)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.payments.config import get_payments_config


def split(order):
    """How one paid order is shared. rider + hotel + platform = what the customer paid."""
    from app.payments.service import Split

    rider = order.rider_fee_in_till
    hotel = order.food_net - order.commission_amount
    platform = order.commission_amount + order.service_fee - order.platform_bonus
    return Split(rider_fee=rider, hotel_id=order.hotel_id, hotel_share=hotel, platform_fee=platform)


async def on_delivered(session: AsyncSession, order) -> None:
    if not get_payments_config().payments_enabled or order.payment_method != "mpesa":
        return
    from app.payments import confirm_delivery
    from app.services import push

    sp = split(order)
    rider_id = order.rider_id
    if rider_id is None:
        return
    credited = await confirm_delivery(
        session,
        str(order.id),
        rider_id,
        sp.rider_fee,
        hotel_id=sp.hotel_id,
        hotel_share=sp.hotel_share,
        platform_fee=sp.platform_fee,
    )
    if credited:
        push.notify(
            session,
            title=f"+KES {credited} added",
            body=f"Delivery #{order.code} is in your wallet",
            url="/rider",
            tag=f"wallet-{order.id}",
            rider_id=rider_id,
        )


async def on_handover(session: AsyncSession, order) -> None:
    """Pickup / eat-in order handed over at the counter: no rider, hotel and platform only."""
    if not get_payments_config().payments_enabled or order.payment_method != "mpesa":
        return
    from app.payments.service import confirm_handover

    sp = split(order)
    await confirm_handover(
        session,
        str(order.id),
        hotel_id=sp.hotel_id,
        hotel_share=sp.hotel_share,
        platform_fee=sp.platform_fee,
    )


async def eligible_riders(session: AsyncSession) -> dict:
    """Riders who may be paid: approved, with an M-Pesa number. App-side knowledge, so it lives
    here at the boundary and not inside the module."""
    from sqlalchemy import select

    from app.models import RiderProfile

    rows = await session.execute(
        select(RiderProfile.user_id, RiderProfile.mpesa_number).where(
            RiderProfile.kyc_status == "approved", RiderProfile.mpesa_number != ""
        )
    )
    return {uid: phone for uid, phone in rows.all()}


async def eligible_hotels(session: AsyncSession) -> dict:
    """Hotels that can be paid, and where: hotel_id -> (channel, destination, name)."""
    from sqlalchemy import select

    from app.models import Hotel

    to_till = get_payments_config().settle_hotels_to_till
    rows = await session.execute(select(Hotel.id, Hotel.till_number, Hotel.phone, Hotel.name))
    out = {}
    for hid, till, phone, name in rows.all():
        if to_till and till:
            out[hid] = ("till", till, name)
        elif phone:
            out[hid] = ("phone", phone, name)
    return out


# --- STK checkout --------------------------------------------------------------------------


async def stk_enabled_for(session: AsyncSession, hotel_id) -> bool:
    """Real STK checkout needs every switch: module on, NOT shadow, checkout on, hotel on."""
    cfg = get_payments_config()
    if not (cfg.payments_enabled and cfg.payments_stk_checkout) or cfg.payments_shadow:
        return False
    from sqlalchemy import select

    from app.payments.models import HotelFlag

    return bool(
        await session.scalar(select(HotelFlag.stk_enabled).where(HotelFlag.hotel_id == hotel_id))
    )


async def start_checkout(session: AsyncSession, order):
    """Send the customer an M-Pesa prompt for this order. Returns the StkRequest, or None when
    this order is not paid this way (so the pilot Till flow carries on exactly as before)."""
    if order.payment_method != "mpesa" or not await stk_enabled_for(session, order.hotel_id):
        return None
    from app.payments import collection

    sp = split(order)
    return await collection.start_stk(
        session,
        order_ref=str(order.id),
        account_ref=order.code,
        phone=order.customer_phone,
        amount=order.till_amount,
        rider_fee=sp.rider_fee,
        hotel_id=sp.hotel_id,
        hotel_share=sp.hotel_share,
        platform_fee=sp.platform_fee,
    )


async def stk_status(session: AsyncSession, order_id) -> str | None:
    """Latest STK attempt for an order (for the tracking page), or None."""
    from sqlalchemy import select

    from app.payments.models import StkRequest

    rows = (
        await session.execute(
            select(StkRequest.status, StkRequest.created_at)
            .where(StkRequest.order_ref == str(order_id))
            .order_by(StkRequest.created_at.desc())
        )
    ).all()
    if not rows:
        return None
    states = [r[0] for r in rows]
    # A live or settled attempt wins over an older failed one (attempts can share a timestamp).
    for live in ("success", "review", "sent"):
        if live in states:
            return live
    return states[0]


async def refund_info(session: AsyncSession, order_id) -> tuple[str | None, int | None]:
    """(status, amount) of the customer's refund for this order, for the tracking page."""
    from sqlalchemy import select

    from app.payments.models import CustomerRefund

    row = (
        await session.execute(
            select(CustomerRefund.status, CustomerRefund.amount)
            .where(CustomerRefund.order_ref == str(order_id))
            .order_by(CustomerRefund.attempt.desc())
            .limit(1)
        )
    ).first()
    return (row[0], row[1]) if row else (None, None)


async def mark_order_paid(session: AsyncSession, order_ref: str) -> bool:
    """An STK payment was confirmed: the order becomes Paid, once. Deliberately does NOT write the
    pilot's Till ledger entries: the platform holds this money, the hotel never received it."""
    import uuid
    from datetime import UTC, datetime

    from sqlalchemy import select, update

    from app.core.time import utcnow
    from app.models import Order, OrderEvent
    from app.services import events

    try:
        oid = uuid.UUID(order_ref)
    except ValueError:
        return False
    order = await session.scalar(select(Order).where(Order.id == oid).with_for_update())
    if order is None:
        return False
    if order.status not in ("awaiting_payment", "checking_payment"):
        # Paid by another way, expired or cancelled meanwhile: the money is held, so give it back.
        await refund_stk_order(
            session, order, f"payment arrived after the order was {order.status}"
        )
        return False
    now = utcnow()
    previous = order.status
    res = await session.execute(
        update(Order)
        .where(Order.id == order.id, Order.status == previous)
        .values(status="paid", paid_at=now, closed_at=None)
    )
    if res.rowcount != 1:
        return False
    await session.refresh(order)
    session.add(
        OrderEvent(order_id=order.id, from_status=previous, to_status="paid", actor_type="system")
    )
    events.order_changed(session, order, {"new_paid": True})  # rings the hotel's order screen
    _ = (UTC, datetime)
    return True


async def refund_stk_order(session: AsyncSession, order, why: str) -> int:
    """Give a customer their STK payment back: holds move to their refund balance and a refund
    is queued (sent within a minute by the scheduler). Returns the KES being refunded."""
    from sqlalchemy import select

    from app.payments import refunds, reverse
    from app.payments.models import StkRequest
    from app.services import payments

    ref = str(order.id)
    owed = await reverse(session, ref)
    if owed <= 0:
        return 0
    phone = await session.scalar(
        select(StkRequest.phone).where(StkRequest.order_ref == ref, StkRequest.status == "success")
    )
    row = await refunds.queue_refund(
        session, order_ref=ref, phone=phone or "", amount=owed, reason=why
    )
    if row is None or not phone:
        await payments.open_review(
            session,
            type="overpaid",
            hotel_id=order.hotel_id,
            order_id=order.id,
            reason=f"Refund the customer KES {owed:,} (order {order.status}): {why}",
        )
    return owed


async def on_cancelled(session: AsyncSession, order) -> None:
    """Rejected or cancelled order: if the customer paid by STK, refund them automatically."""
    cfg = get_payments_config()
    if not cfg.payments_enabled or cfg.payments_shadow:
        return
    from app.payments.service import _collected

    if await _collected(session, str(order.id)):
        await refund_stk_order(session, order, f"order {order.status}")


async def stk_needs_review(session: AsyncSession, req) -> None:
    """A payment arrived that the module will not confirm by itself (wrong amount, no receipt).
    The money is in the Paybill but not held for anyone: a person decides."""
    from sqlalchemy import select

    from app.models import Order
    from app.services import payments

    try:
        import uuid

        order = await session.scalar(select(Order).where(Order.id == uuid.UUID(req.order_ref)))
    except ValueError:
        return
    if order is None:
        return
    await payments.open_review(
        session,
        type="overpaid",
        hotel_id=order.hotel_id,
        order_id=order.id,
        reason=(
            f"STK payment needs checking: order total KES {order.till_amount:,}, "
            f"result {req.result_code} ({req.result_desc or 'no receipt'}). "
            "Check the M-Pesa statement, then refund or confirm by hand."
        ),
    )
