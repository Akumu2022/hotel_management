"""The module's narrow interface. Knows only order refs, party ids, amounts: no menus, no routes.

One paid order is split three ways (the app layer works the numbers out, see hook.split):
  rider fee      -> held for whoever delivers (platform/pending), credited to the rider on delivery
  hotel share    -> the hotel's pending money, available on delivery or hand-over
  platform fee   -> commission + service fee, held until delivery, then the platform's earnings
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments import ledger, outbox
from app.payments.config import get_payments_config
from app.payments.models import WalletEntry


@dataclass(frozen=True)
class Split:
    rider_fee: int = 0
    hotel_id: uuid.UUID | None = None
    hotel_share: int = 0
    platform_fee: int = 0

    @property
    def total(self) -> int:
        return self.rider_fee + self.hotel_share + self.platform_fee


async def held(session: AsyncSession, order_ref: str, kind: str) -> int:
    """What is still held for this order under `kind` (rider_fee / hotel_share / platform_fee)."""
    q = select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(
        WalletEntry.order_ref == order_ref,
        WalletEntry.kind.like(kind + r"\_%"),
        WalletEntry.bucket == "pending",
    )
    return int(await session.scalar(q))


async def _collected(session: AsyncSession, order_ref: str) -> bool:
    return bool(
        await session.scalar(
            select(WalletEntry.id)
            .where(WalletEntry.order_ref == order_ref, WalletEntry.kind.like("%\\_held"))
            .limit(1)
        )
    )


async def request_collection(
    session: AsyncSession,
    order_ref: str,
    rider_fee: int = 0,
    *,
    hotel_id: uuid.UUID | None = None,
    hotel_share: int = 0,
    platform_fee: int = 0,
) -> bool:
    """The customer's payment for this order is in: hold each part against the order. The STK
    Push itself lives in collection.start_stk."""
    shadow = get_payments_config().payments_shadow
    did = False
    if rider_fee > 0:
        did |= await ledger.move(
            session,
            idem_key=f"collect:{order_ref}:rider",
            party_type="platform",
            party_id=None,
            src=None,
            dst="pending",
            amount=rider_fee,
            kind="rider_fee_held",
            order_ref=order_ref,
            shadow=shadow,
        )
    if hotel_share > 0 and hotel_id is not None:
        did |= await ledger.move(
            session,
            idem_key=f"collect:{order_ref}:hotel",
            party_type="hotel",
            party_id=hotel_id,
            src=None,
            dst="pending",
            amount=hotel_share,
            kind="hotel_share_held",
            order_ref=order_ref,
            shadow=shadow,
        )
    if platform_fee > 0:
        did |= await ledger.move(
            session,
            idem_key=f"collect:{order_ref}:fee",
            party_type="platform",
            party_id=None,
            src=None,
            dst="pending",
            amount=platform_fee,
            kind="platform_fee_held",
            order_ref=order_ref,
            shadow=shadow,
        )
    return did


async def _release_to_owners(
    session: AsyncSession, order_ref: str, hotel_id: uuid.UUID | None, shadow: bool
) -> int:
    """Hotel share -> available, platform fee -> earned. Returns the hotel share released."""
    released = 0
    hotel_part = await held(session, order_ref, "hotel_share")
    if hotel_part > 0 and hotel_id is not None:
        await ledger.move(
            session,
            idem_key=f"deliver:{order_ref}:hotel",
            party_type="hotel",
            party_id=hotel_id,
            src="pending",
            dst="available",
            amount=hotel_part,
            kind="hotel_share_credit",
            order_ref=order_ref,
            shadow=shadow,
        )
        released = hotel_part
    fee = await held(session, order_ref, "platform_fee")
    if fee > 0:
        await ledger.move(
            session,
            idem_key=f"deliver:{order_ref}:fee",
            party_type="platform",
            party_id=None,
            src="pending",
            dst="earned",
            amount=fee,
            kind="platform_fee_earned",
            order_ref=order_ref,
            shadow=shadow,
        )
    return released


async def confirm_delivery(
    session: AsyncSession,
    order_ref: str,
    rider_id: uuid.UUID,
    rider_fee: int = 0,
    *,
    hotel_id: uuid.UUID | None = None,
    hotel_share: int = 0,
    platform_fee: int = 0,
) -> int:
    """Delivery code accepted. In the CALLER's transaction: the rider's fee becomes theirs, the
    hotel's share becomes available, the platform fee is earned. Returns the KES credited to the
    rider now (0 if nothing to do or already done). No Daraja call, no queue, no admin step.
    Orders never paid through this module are ignored, except in shadow mode, where the money
    is recorded as if they had been."""
    cfg = get_payments_config()
    if not cfg.payments_enabled:
        return 0
    if not await _collected(session, order_ref):
        if not cfg.payments_shadow:
            return 0
        await request_collection(
            session,
            order_ref,
            rider_fee,
            hotel_id=hotel_id,
            hotel_share=hotel_share,
            platform_fee=platform_fee,
        )
    credited = 0
    rider_part = await held(session, order_ref, "rider_fee")
    if rider_part > 0:
        # Paid out of THIS order's hold, to the rider who entered the correct delivery code.
        moved = await ledger.transfer(
            session,
            idem_key=f"deliver:{order_ref}:rider",
            src=("platform", None, "pending"),
            dst=("rider", rider_id, "available"),
            amount=rider_part,
            kind="rider_fee_credit",
            order_ref=order_ref,
            shadow=cfg.payments_shadow,
        )
        credited = rider_part if moved else 0
    await _release_to_owners(session, order_ref, hotel_id, cfg.payments_shadow)
    if credited:
        outbox.publish(
            session,
            "wallet.credited",
            {"order_ref": order_ref, "rider_id": str(rider_id), "amount": credited},
        )
    return credited


async def confirm_handover(
    session: AsyncSession,
    order_ref: str,
    *,
    hotel_id: uuid.UUID,
    hotel_share: int = 0,
    platform_fee: int = 0,
) -> int:
    """Pickup / eat-in order handed over: no rider, so only the hotel and platform parts move.
    Returns the hotel share made available."""
    cfg = get_payments_config()
    if not cfg.payments_enabled:
        return 0
    if not await _collected(session, order_ref):
        if not cfg.payments_shadow:
            return 0
        await request_collection(
            session,
            order_ref,
            0,
            hotel_id=hotel_id,
            hotel_share=hotel_share,
            platform_fee=platform_fee,
        )
    return await _release_to_owners(session, order_ref, hotel_id, cfg.payments_shadow)


async def reverse(session: AsyncSession, order_ref: str, rider_fee: int = 0) -> int:
    """Order rejected/cancelled before delivery: every hold moves to the CUSTOMER's refund
    balance for this order (still counted as owed, so the float check covers it). Returns the
    KES now owed back to the customer (0 if nothing was held or it was already reversed). Money
    already credited to a rider or hotel is never reversed automatically."""
    cfg = get_payments_config()
    if not cfg.payments_enabled or not await _collected(session, order_ref):
        return 0
    try:
        customer = uuid.UUID(order_ref)  # the refund balance is kept per order
    except ValueError:
        return 0
    shadow = cfg.payments_shadow
    hotel_id = await session.scalar(
        select(WalletEntry.party_id).where(
            WalletEntry.order_ref == order_ref, WalletEntry.kind == "hotel_share_held"
        )
    )
    total = 0
    for kind, src in (
        ("rider_fee", ("platform", None, "pending")),
        ("platform_fee", ("platform", None, "pending")),
        ("hotel_share", ("hotel", hotel_id, "pending")),
    ):
        amount = await held(session, order_ref, kind)
        if amount <= 0:
            continue
        await ledger.transfer(
            session,
            idem_key=f"reverse:{order_ref}:{kind}",
            src=src,
            dst=("customer", customer, "reserved"),
            amount=amount,
            kind=f"{kind}_released",
            order_ref=order_ref,
            shadow=shadow,
        )
        total += amount
    return total


async def request_withdrawal(session: AsyncSession, rider_id: uuid.UUID):
    raise NotImplementedError("Use app.payments.payouts.request_withdrawal")


async def get_balance(session: AsyncSession, rider_id: uuid.UUID) -> dict[str, int]:
    """Live ledger balances for the rider's wallet screen."""
    shadow = get_payments_config().payments_shadow
    return {
        b: await ledger.balance(session, "rider", rider_id, b, shadow=shadow)
        for b in ("pending", "available", "reserved", "paid")
    }
