"""The module's narrow interface. Knows only order refs, party ids, amounts: no menus, no routes."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments import ledger, outbox
from app.payments.config import get_payments_config
from app.payments.models import WalletEntry


async def _collected(session: AsyncSession, order_ref: str) -> bool:
    return bool(
        await session.scalar(
            select(WalletEntry.id).where(WalletEntry.idem_key == f"collect:{order_ref}:hold:in")
        )
    )


async def request_collection(session: AsyncSession, order_ref: str, rider_fee: int) -> bool:
    """The customer's payment for this order is in: the rider-fee part is HELD by the platform
    against the order (not yet any rider's). The STK Push itself lives in collection.start_stk."""
    if rider_fee <= 0:
        return False
    return await ledger.move(
        session,
        idem_key=f"collect:{order_ref}:hold",
        party_type="platform",
        party_id=None,
        src=None,
        dst="pending",
        amount=rider_fee,
        kind="rider_fee_held",
        order_ref=order_ref,
        shadow=get_payments_config().payments_shadow,
    )


async def confirm_delivery(
    session: AsyncSession, order_ref: str, rider_id: uuid.UUID, rider_fee: int
) -> int:
    """Pending -> available for the rider, in the CALLER's transaction. Returns the KES credited
    now (0 if nothing to do or already credited). No Daraja call, no queue, no admin step.
    Orders never paid through this module are ignored, except in shadow mode, where the credit
    is recorded as if they had been."""
    cfg = get_payments_config()
    if not cfg.payments_enabled or rider_fee <= 0:
        return 0
    if not await _collected(session, order_ref):
        if not cfg.payments_shadow:
            return 0
        await request_collection(session, order_ref, rider_fee)
    # Paid out of THIS order's hold, to the rider who entered the correct delivery code.
    moved = await ledger.transfer(
        session,
        idem_key=f"deliver:{order_ref}:rider",
        src=("platform", None, "pending"),
        dst=("rider", rider_id, "available"),
        amount=rider_fee,
        kind="rider_fee_credit",
        order_ref=order_ref,
        shadow=cfg.payments_shadow,
    )
    if not moved:
        return 0
    outbox.publish(
        session,
        "wallet.credited",
        {"order_ref": order_ref, "rider_id": str(rider_id), "amount": rider_fee},
    )
    return rider_fee


async def reverse(session: AsyncSession, order_ref: str, rider_fee: int) -> bool:
    """Order rejected/cancelled before delivery: the hold is released (the customer is refunded
    by the refund flow). Money already credited to a rider is never reversed automatically."""
    cfg = get_payments_config()
    if not cfg.payments_enabled or not await _collected(session, order_ref):
        return False
    return await ledger.move(
        session,
        idem_key=f"reverse:{order_ref}:hold",
        party_type="platform",
        party_id=None,
        src="pending",
        dst=None,
        amount=rider_fee,
        kind="rider_fee_released",
        order_ref=order_ref,
        shadow=cfg.payments_shadow,
    )


async def request_withdrawal(session: AsyncSession, rider_id: uuid.UUID):
    raise NotImplementedError("Payouts arrive with the Daraja B2C adapter")


async def get_balance(session: AsyncSession, rider_id: uuid.UUID) -> dict[str, int]:
    """Live ledger balances for the rider's wallet screen."""
    shadow = get_payments_config().payments_shadow
    return {
        b: await ledger.balance(session, "rider", rider_id, b, shadow=shadow)
        for b in ("pending", "available", "reserved", "paid")
    }
