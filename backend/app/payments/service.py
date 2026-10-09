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
            select(WalletEntry.id).where(WalletEntry.idem_key == f"collect:{order_ref}:rider:in")
        )
    )


async def request_collection(
    session: AsyncSession, order_ref: str, rider_id: uuid.UUID, rider_fee: int
) -> bool:
    """Record that the customer's payment covered the rider fee: it sits as the rider's PENDING
    money until delivery. (The STK Push to Daraja arrives with the Daraja adapter.)"""
    if rider_fee <= 0:
        return False
    return await ledger.move(
        session,
        idem_key=f"collect:{order_ref}:rider",
        party_type="rider",
        party_id=rider_id,
        src=None,
        dst="pending",
        amount=rider_fee,
        kind="rider_fee_pending",
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
        await request_collection(session, order_ref, rider_id, rider_fee)
    moved = await ledger.move(
        session,
        idem_key=f"deliver:{order_ref}:rider",
        party_type="rider",
        party_id=rider_id,
        src="pending",
        dst="available",
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


async def reverse(
    session: AsyncSession, order_ref: str, rider_id: uuid.UUID, rider_fee: int
) -> bool:
    """Order rejected/cancelled before delivery: pending money is withdrawn. Money already made
    available is never reversed automatically (an admin adjustment handles disputes)."""
    cfg = get_payments_config()
    if not cfg.payments_enabled or not await _collected(session, order_ref):
        return False
    return await ledger.move(
        session,
        idem_key=f"reverse:{order_ref}:rider",
        party_type="rider",
        party_id=rider_id,
        src="pending",
        dst=None,
        amount=rider_fee,
        kind="rider_fee_reversed",
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
