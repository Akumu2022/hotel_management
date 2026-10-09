"""The only code the pilot calls: one additive call after delivery is confirmed. It does nothing
while PAYMENTS_ENABLED is off. A failure here propagates, so the delivery rolls back and the
rider simply enters the code again (credited exactly once, by idempotency)."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.payments.config import get_payments_config


async def on_delivered(session: AsyncSession, order) -> None:
    if not get_payments_config().payments_enabled:
        return
    if order.rider_fee_mode != "included" or not order.rider_id or not order.rider_fee:
        return  # option B (cash) and no-fee orders never enter the wallet
    from app.payments import confirm_delivery
    from app.services import push

    credited = await confirm_delivery(session, str(order.id), order.rider_id, order.rider_fee)
    if credited:
        push.notify(
            session,
            title=f"+KES {credited} added",
            body=f"Delivery #{order.code} is in your wallet",
            url="/rider",
            tag=f"wallet-{order.id}",
            rider_id=order.rider_id,
        )
