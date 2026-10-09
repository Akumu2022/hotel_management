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
