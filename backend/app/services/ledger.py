"""Append-only money ledger.

Every function runs inside the caller's transaction and is idempotent: entries are inserted
with ON CONFLICT DO NOTHING against the unique (order|refund|statement|settlement|payout,
entry_type) indexes, so a repeat writes nothing. Balances are always sums of entries.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.time import utcnow
from app.models import ENTRY_TYPES, LedgerEntry, Order, Refund
from app.services import events
from app.services.pricing import pct

PAYMENT_IN = ("till_received", "cash_received")


async def _write(
    session: AsyncSession,
    entry_type: str,
    amount: int,
    *,
    from_id: uuid.UUID | None = None,
    to_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
    refund_id: uuid.UUID | None = None,
    statement_id: uuid.UUID | None = None,
    settlement_id: uuid.UUID | None = None,
    payout_id: uuid.UUID | None = None,
    reference: str | None = None,
    created_by: uuid.UUID | None = None,
    at: datetime | None = None,
) -> bool:
    """Insert one entry. Returns False when it already existed (or amount is 0). `at` stamps
    it with the caller's clock (billing compares it with statement weeks); default: DB time."""
    if amount < 0:
        raise ValueError("ledger amounts are positive; use a reversal entry type")
    if amount == 0:
        return False
    kind, from_party, to_party = ENTRY_TYPES[entry_type]
    stmt = (
        insert(LedgerEntry)
        .values(
            entry_type=entry_type,
            kind=kind,
            from_party=from_party,
            from_id=from_id,
            to_party=to_party,
            to_id=to_id,
            amount=amount,
            order_id=order_id,
            refund_id=refund_id,
            statement_id=statement_id,
            settlement_id=settlement_id,
            payout_id=payout_id,
            reference=reference,
            created_by=created_by,
            **({"created_at": at} if at is not None else {}),
        )
        .on_conflict_do_nothing()
    )
    result = await session.execute(stmt)
    return result.rowcount == 1


# --- Orders -----------------------------------------------------------------------------------


async def record_payment(
    session: AsyncSession,
    order: Order,
    *,
    amount: int,
    method: str = "mpesa",
    reference: str | None = None,
    created_by: uuid.UUID | None = None,
) -> None:
    """Money reached the hotel (Till or cash) plus the commission and service fee it now owes.
    Called in the same transaction that moves the order to Paid / Collected."""
    entry = "till_received" if method == "mpesa" else "cash_received"
    common = {"order_id": order.id, "created_by": created_by}
    await _write(session, entry, amount, to_id=order.hotel_id, reference=reference, **common)
    await _write(session, "commission", order.commission_amount, from_id=order.hotel_id, **common)
    await _write(session, "service_fee", order.service_fee, from_id=order.hotel_id, **common)
    # The customer paid less by this much; the platform makes it up to the hotel.
    await _write(session, "bonus_credit", order.platform_bonus, to_id=order.hotel_id, **common)


async def record_rider_fee(
    session: AsyncSession,
    order: Order,
    *,
    rider_id: uuid.UUID,
    payout_mode: str,
    created_by: uuid.UUID | None = None,
) -> None:
    """The rider fee for a delivery (spec section 8 table)."""
    common = {"order_id": order.id, "created_by": created_by}
    if order.rider_fee_mode == "included" and payout_mode == "instant":
        await _write(
            session,
            "rider_fee_instant",
            order.rider_fee,
            from_id=order.hotel_id,
            to_id=rider_id,
            **common,
        )
    elif order.rider_fee_mode == "included":
        await _write(session, "rider_fee_held", order.rider_fee, from_id=order.hotel_id, **common)
        await _write(session, "rider_fee_owed", order.rider_fee, to_id=rider_id, **common)
    elif order.rider_fee_mode == "cash":
        await _write(session, "rider_fee_cash", order.rider_fee, to_id=rider_id, **common)
    else:
        raise ValueError("pickup orders have no rider fee")


async def credit_failed_delivery(
    session: AsyncSession, order: Order, *, amount: int, created_by: uuid.UUID | None
) -> None:
    """Rider-fault failed delivery: the hotel refunded the customer; the platform owes the
    hotel that amount on its statement."""
    await _write(
        session,
        "failed_delivery_credit",
        amount,
        to_id=order.hotel_id,
        order_id=order.id,
        created_by=created_by,
    )


async def record_rider_compensation(
    session: AsyncSession, order: Order, *, rider_id: uuid.UUID, created_by: uuid.UUID | None
) -> None:
    """Option B fee not paid by the customer: the platform owes the rider."""
    await _write(
        session,
        "rider_compensation",
        order.rider_fee,
        to_id=rider_id,
        order_id=order.id,
        created_by=created_by,
    )


# --- Refunds -----------------------------------------------------------------------------


async def amount_paid(session: AsyncSession, order_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
        LedgerEntry.order_id == order_id, LedgerEntry.entry_type.in_(PAYMENT_IN)
    )
    return int((await session.execute(stmt)).scalar_one())


async def amount_refunded(session: AsyncSession, order_id: uuid.UUID) -> int:
    """Total of approved refunds for an order (sent or not)."""
    stmt = select(func.coalesce(func.sum(Refund.amount), 0)).where(Refund.order_id == order_id)
    return int((await session.execute(stmt)).scalar_one())


async def refund_rest(
    session: AsyncSession,
    order: Order,
    *,
    reason: str,
    approved_by: uuid.UUID | None,
    refund_id: uuid.UUID | None = None,
) -> Refund | None:
    """Refund everything received for the order and not already refunded, split food ->
    service fee -> rider fee -> extra. Less than the full total may have come in (an accepted
    shortfall, or a platform bonus), so the parts are worked out from what was paid."""
    if refund_id is not None and (existing := await session.get(Refund, refund_id)):
        return existing
    rest = await amount_paid(session, order.id) - await amount_refunded(session, order.id)
    if rest <= 0:
        return None
    food = min(order.food_net, rest)
    fee = min(order.service_fee, rest - food)
    rider = min(order.rider_fee_in_till, rest - food - fee)
    return await approve_refund(
        session,
        order.id,
        food=food,
        service_fee=fee,
        rider_fee=rider,
        excess=rest - food - fee - rider,
        reason=reason,
        approved_by=approved_by,
        refund_id=refund_id,
    )


async def approve_refund(
    session: AsyncSession,
    order_id: uuid.UUID,
    *,
    food: int = 0,
    service_fee: int = 0,
    rider_fee: int = 0,
    excess: int = 0,
    reason: str,
    approved_by: uuid.UUID | None,
    refund_id: uuid.UUID | None = None,
) -> Refund:
    """Create a refund record and reverse commission pro rata, cumulatively:
    reversed_total = floor(rate x food refunded so far) (percent deals) or
    floor(fee x food refunded / food) (flat tiers); this refund reverses the difference.
    Once everything paid has been refunded, the whole commission, the service fee and any
    platform bonus are reversed.
    `refund_id` (client-generated) makes a repeated request return the same refund."""
    order = (
        await session.execute(select(Order).where(Order.id == order_id).with_for_update())
    ).scalar_one_or_none()
    if order is None:
        raise AppError(404, "not_found", "Order not found")
    if refund_id is not None:
        existing = await session.get(Refund, refund_id)
        if existing is not None:
            if existing.order_id != order.id:
                raise AppError(409, "refund_id_conflict", "Refund ID belongs to another order")
            return existing

    paid = await amount_paid(session, order.id)
    if paid == 0:
        raise AppError(409, "not_paid", "Nothing has been paid for this order")

    prior = (
        await session.execute(
            select(
                func.coalesce(func.sum(Refund.amount), 0),
                func.coalesce(func.sum(Refund.food_amount), 0),
                func.coalesce(func.sum(Refund.service_fee_amount), 0),
                func.coalesce(func.sum(Refund.rider_fee_amount), 0),
                func.coalesce(func.sum(Refund.excess_amount), 0),
            ).where(Refund.order_id == order.id)
        )
    ).one()
    prior_total, prior_food, prior_sf, prior_rider, prior_excess = (int(v) for v in prior)
    amount = food + service_fee + rider_fee + excess

    if min(food, service_fee, rider_fee, excess) < 0 or amount == 0:
        raise AppError(422, "bad_refund", "Refund parts must be positive whole shillings")
    limits = [
        (prior_food + food, order.food_net, "food"),
        (prior_sf + service_fee, order.service_fee, "service fee"),
        (prior_rider + rider_fee, order.rider_fee_in_till, "rider fee"),
        (prior_excess + excess, max(paid - order.till_amount, 0), "overpayment"),
        (prior_total + amount, paid, "amount paid"),
    ]
    for total, limit, label in limits:
        if total > limit:
            raise AppError(409, "refund_exceeds_paid", f"Refund would exceed the {label}")

    refund = Refund(
        id=refund_id or uuid.uuid4(),
        order_id=order.id,
        amount=amount,
        food_amount=food,
        service_fee_amount=service_fee,
        rider_fee_amount=rider_fee,
        excess_amount=excess,
        reason=reason,
        approved_by=approved_by,
    )
    session.add(refund)
    await session.flush()

    common = {"order_id": order.id, "refund_id": refund.id, "created_by": approved_by}
    everything = prior_total + amount == paid
    reversed_so_far = await _sum_entries(session, order.id, "commission_reversal")
    food_so_far = prior_food + food
    if everything:
        target = order.commission_amount
    elif order.commission_bp:
        target = pct(order.commission_bp, food_so_far)
    else:
        target = order.commission_amount * food_so_far // order.food_net if order.food_net else 0
    await _write(
        session, "commission_reversal", target - reversed_so_far, to_id=order.hotel_id, **common
    )
    if everything and order.platform_bonus:
        await _write(
            session,
            "bonus_credit_reversal",
            order.platform_bonus,
            from_id=order.hotel_id,
            **common,
        )
    if everything:
        already = await _sum_entries(session, order.id, "service_fee_reversal")
        await _write(
            session,
            "service_fee_reversal",
            order.service_fee - already,
            to_id=order.hotel_id,
            **common,
        )
    _refund_event(session, order)
    return refund


def _refund_event(session: AsyncSession, order: Order) -> None:
    """Refunds to send ring the hotel until marked sent."""
    events.emit(session, f"hotel:{order.hotel_id}", {"type": "refund", "order_id": str(order.id)})
    events.emit(session, "admin", {"type": "refund", "order_id": str(order.id)})


async def mark_refund_sent(
    session: AsyncSession, refund_id: uuid.UUID, *, mpesa_code: str, sent_by: uuid.UUID | None
) -> Refund:
    """Record the M-Pesa code of a refund the hotel sent. Repeating with the same code is a
    no-op; a different code for an already-sent refund is a conflict."""
    mpesa_code = mpesa_code.strip().upper()
    result = await session.execute(
        update(Refund)
        .where(Refund.id == refund_id, Refund.status == "approved")
        .values(status="sent", mpesa_code=mpesa_code, sent_at=utcnow(), sent_by=sent_by)
        .returning(Refund)
    )
    refund = result.scalar_one_or_none()
    if refund is None:
        refund = await session.get(Refund, refund_id)
        if refund is None:
            raise AppError(404, "not_found", "Refund not found")
        if refund.mpesa_code != mpesa_code:
            raise AppError(409, "already_sent", "This refund was already recorded as sent")
        return refund
    order = await session.get(Order, refund.order_id)
    await _write(
        session,
        "refund",
        refund.amount,
        from_id=order.hotel_id,
        order_id=order.id,
        refund_id=refund.id,
        reference=mpesa_code,
        created_by=sent_by,
    )
    _refund_event(session, order)
    return refund


async def _sum_entries(session: AsyncSession, order_id: uuid.UUID, entry_type: str) -> int:
    stmt = select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
        LedgerEntry.order_id == order_id, LedgerEntry.entry_type == entry_type
    )
    return int((await session.execute(stmt)).scalar_one())


# --- Balances ---------------------------------------------------------------------------------


def _party(col_party, col_id, party: str, party_id: uuid.UUID | None):
    return (col_party == party) & col_id.is_not_distinct_from(party_id)


async def owed(
    session: AsyncSession,
    debtor: tuple[str, uuid.UUID | None],
    creditor: tuple[str, uuid.UUID | None],
    *,
    order_id: uuid.UUID | None = None,
) -> int:
    """Net amount `debtor` owes `creditor`: obligations each way, less payments each way.
    Negative means the creditor owes the debtor."""
    e = LedgerEntry
    d_to_c = _party(e.from_party, e.from_id, *debtor) & _party(e.to_party, e.to_id, *creditor)
    c_to_d = _party(e.from_party, e.from_id, *creditor) & _party(e.to_party, e.to_id, *debtor)
    is_obl = e.kind == "obligation"
    signed = case(
        (d_to_c & is_obl, e.amount),
        (c_to_d & is_obl, -e.amount),
        (d_to_c, -e.amount),
        (c_to_d, e.amount),
        else_=0,
    )
    stmt = select(func.coalesce(func.sum(signed), 0))
    if order_id is not None:
        stmt = stmt.where(e.order_id == order_id)
    return int((await session.execute(stmt)).scalar_one())


async def cash_held(
    session: AsyncSession, party: str, party_id: uuid.UUID | None, *, order_id=None
) -> int:
    """Money that has physically reached `party`, less money it has paid out."""
    e = LedgerEntry
    incoming = _party(e.to_party, e.to_id, party, party_id)
    outgoing = _party(e.from_party, e.from_id, party, party_id)
    signed = case(
        (incoming & (e.kind == "payment"), e.amount),
        (outgoing & (e.kind == "payment"), -e.amount),
        else_=0,
    )
    stmt = select(func.coalesce(func.sum(signed), 0))
    if order_id is not None:
        stmt = stmt.where(e.order_id == order_id)
    return int((await session.execute(stmt)).scalar_one())


@dataclass(frozen=True)
class HotelPosition:
    cash_held: int
    owed_to_platform: int

    @property
    def keeps(self) -> int:
        return self.cash_held - self.owed_to_platform


async def hotel_position(
    session: AsyncSession, hotel_id: uuid.UUID, *, order_id: uuid.UUID | None = None
) -> HotelPosition:
    return HotelPosition(
        cash_held=await cash_held(session, "hotel", hotel_id, order_id=order_id),
        owed_to_platform=await owed(
            session, ("hotel", hotel_id), ("platform", None), order_id=order_id
        ),
    )


async def refund_unaccepted(
    session: AsyncSession,
    order: Order,
    *,
    amount: int,
    reference: str,
    reason: str,
    approved_by: uuid.UUID | None,
    refund_id: uuid.UUID,
) -> Refund:
    """Money that reached the Till but was never accepted for the order (underpaid and
    refunded, or paid after expiry and refunded). It is recorded as received and returned in
    full, with no commission or service fee: the hotel earned nothing from it."""
    existing = await session.get(Refund, refund_id)
    if existing is not None:
        return existing
    await _write(
        session,
        "till_received",
        amount,
        to_id=order.hotel_id,
        order_id=order.id,
        reference=reference,
        created_by=approved_by,
    )
    refund = Refund(
        id=refund_id,
        order_id=order.id,
        amount=amount,
        food_amount=0,
        service_fee_amount=0,
        rider_fee_amount=0,
        excess_amount=amount,
        reason=reason,
        approved_by=approved_by,
    )
    session.add(refund)
    await session.flush()
    _refund_event(session, order)
    return refund
