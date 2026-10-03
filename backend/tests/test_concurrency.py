"""Spec section 13: the same money action fired many times at once has exactly one effect.
These use real commits on separate connections."""

import asyncio
import uuid

from sqlalchemy import func, select

from app.models import LedgerEntry, Order, Refund
from app.services import ledger
from tests.factories import make_hotel, make_order

N = 20


async def _setup(committed, paid: bool = False):
    async with committed() as s:
        hotel = await make_hotel(s)
        order = await make_order(s, hotel)
        if paid:
            await ledger.record_payment(s, order, amount=order.till_amount)
        await s.commit()
        return hotel.id, order.id


async def test_concurrent_payment_recording_writes_once(committed):
    _, order_id = await _setup(committed)

    async def confirm():
        async with committed() as s, s.begin():
            order = await s.get(Order, order_id)
            await ledger.record_payment(s, order, amount=order.till_amount, reference="TJ1")

    await asyncio.gather(*(confirm() for _ in range(N)))

    async with committed() as s:
        rows = await s.execute(
            select(LedgerEntry.entry_type, func.count())
            .where(LedgerEntry.order_id == order_id)
            .group_by(LedgerEntry.entry_type)
        )
        assert dict(rows.all()) == {"till_received": 1, "commission": 1, "service_fee": 1}


async def test_concurrent_refunds_never_exceed_paid(committed):
    hotel_id, order_id = await _setup(committed, paid=True)

    async def refund():
        async with committed() as s:
            try:
                async with s.begin():
                    await ledger.approve_refund(
                        s, order_id, food=400, reason="race", approved_by=None
                    )
                return True
            except Exception:
                return False

    results = await asyncio.gather(*(refund() for _ in range(N)))
    assert results.count(True) == 1  # 400 + 400 > 650 food

    async with committed() as s:
        total = (
            await s.execute(select(func.sum(Refund.amount)).where(Refund.order_id == order_id))
        ).scalar_one()
        assert total == 400
        reversal = (
            await s.execute(
                select(func.sum(LedgerEntry.amount)).where(
                    LedgerEntry.order_id == order_id,
                    LedgerEntry.entry_type == "commission_reversal",
                )
            )
        ).scalar_one()
        assert reversal == 40


async def test_concurrent_same_refund_id_creates_one(committed):
    _, order_id = await _setup(committed, paid=True)
    rid = uuid.uuid4()

    async def refund():
        async with committed() as s, s.begin():
            await ledger.approve_refund(
                s, order_id, food=100, reason="r", approved_by=None, refund_id=rid
            )

    await asyncio.gather(*(refund() for _ in range(N)))
    async with committed() as s:
        count = (
            await s.execute(
                select(func.count()).select_from(Refund).where(Refund.order_id == order_id)
            )
        ).scalar_one()
        assert count == 1
