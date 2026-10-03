import uuid

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from app.core.errors import AppError
from app.models import LedgerEntry
from app.services import ledger
from app.services.settings import HotelRates
from tests.factories import make_hotel, make_order, make_user


async def entries(db, order_id) -> dict[str, int]:
    rows = await db.execute(
        select(LedgerEntry.entry_type, func.sum(LedgerEntry.amount))
        .where(LedgerEntry.order_id == order_id)
        .group_by(LedgerEntry.entry_type)
    )
    return {t: int(a) for t, a in rows.all()}


async def paid_order(db, **kw):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel, **kw)
    method = kw.get("payment_method", "mpesa")
    await ledger.record_payment(db, order, amount=order.till_amount, method=method, reference="TJ1")
    return hotel, order


# --- Payment and hotel net (section 11) ---------------------------------------------------------


async def test_payment_entries(db):
    _, order = await paid_order(db)
    assert await entries(db, order.id) == {
        "till_received": 770,
        "commission": 65,
        "service_fee": 20,
    }


async def test_payment_is_idempotent(db):
    _, order = await paid_order(db)
    for _ in range(3):
        await ledger.record_payment(db, order, amount=order.till_amount, reference="TJ1")
    assert await entries(db, order.id) == {
        "till_received": 770,
        "commission": 65,
        "service_fee": 20,
    }


async def test_cash_pickup(db):
    _, order = await paid_order(
        db, order_type="pickup", rider_fee_mode="none", payment_method="cash"
    )
    assert await entries(db, order.id) == {
        "cash_received": 670,
        "commission": 65,
        "service_fee": 20,
    }


@pytest.mark.parametrize(
    ("order_type", "mode", "payout_mode"),
    [
        ("delivery", "included", "instant"),
        ("delivery", "included", "weekly"),
        ("delivery", "cash", "instant"),
        ("pickup", "none", None),
    ],
)
async def test_hotel_keeps_same_under_every_option(db, order_type, mode, payout_mode):
    hotel, order = await paid_order(db, order_type=order_type, rider_fee_mode=mode)
    rider = None
    if payout_mode:
        rider = await make_user(db, "rider")
        await ledger.record_rider_fee(db, order, rider_id=rider.id, payout_mode=payout_mode)

    pos = await ledger.hotel_position(db, hotel.id)
    assert pos.keeps == 585

    if rider:
        rider_gets = await ledger.cash_held(db, "rider", rider.id) + await ledger.owed(
            db, ("platform", None), ("rider", rider.id)
        )
        assert rider_gets == 100


async def test_weekly_rider_fee_balances(db):
    hotel, order = await paid_order(db)
    rider = await make_user(db, "rider")
    await ledger.record_rider_fee(db, order, rider_id=rider.id, payout_mode="weekly")
    assert await ledger.owed(db, ("hotel", hotel.id), ("platform", None)) == 185
    assert await ledger.owed(db, ("platform", None), ("rider", rider.id)) == 100
    assert await ledger.cash_held(db, "hotel", hotel.id) == 770


async def test_rider_compensation(db):
    _, order = await paid_order(db, rider_fee_mode="cash")
    rider = await make_user(db, "rider")
    await ledger.record_rider_compensation(db, order, rider_id=rider.id, created_by=None)
    await ledger.record_rider_compensation(db, order, rider_id=rider.id, created_by=None)
    assert await ledger.owed(db, ("platform", None), ("rider", rider.id)) == 100


# --- Refunds (D3) -------------------------------------------------------------------------------


async def test_full_refund_reverses_commission_and_service_fee(db):
    hotel, order = await paid_order(db)
    refund = await ledger.approve_refund(
        db, order.id, food=650, service_fee=20, rider_fee=100, reason="rejected", approved_by=None
    )
    await ledger.mark_refund_sent(db, refund.id, mpesa_code="tk9abc", sent_by=None)
    e = await entries(db, order.id)
    assert e["commission_reversal"] == 65
    assert e["service_fee_reversal"] == 20
    assert e["refund"] == 770
    pos = await ledger.hotel_position(db, hotel.id)
    assert (pos.cash_held, pos.owed_to_platform, pos.keeps) == (0, 0, 0)


async def test_partial_refunds_reverse_commission_cumulatively(db):
    hotel = await make_hotel(db)
    # 12.5 % on 333: commission floor(41.625) = 41.
    order = await make_order(
        db, hotel, food=333, rates=HotelRates(commission_bp=1250, service_fee=20, rider_fee=100)
    )
    await ledger.record_payment(db, order, amount=order.till_amount)
    assert order.commission_amount == 41

    reversals = []
    for food in (111, 111, 111):
        r = await ledger.approve_refund(db, order.id, food=food, reason="item", approved_by=None)
        rows = await db.execute(
            select(LedgerEntry.amount).where(
                LedgerEntry.refund_id == r.id, LedgerEntry.entry_type == "commission_reversal"
            )
        )
        reversals.append(rows.scalar_one())
    # floor(12.5 % x 111)=13, floor(x 222)=27 -> 14, floor(x 333)=41 -> 14.
    assert reversals == [13, 14, 14]
    assert sum(reversals) == order.commission_amount
    e = await entries(db, order.id)
    assert "service_fee_reversal" not in e  # not a full refund: service fee and rider fee kept


async def test_service_fee_reversed_only_when_everything_refunded(db):
    _, order = await paid_order(db)
    await ledger.approve_refund(db, order.id, food=650, reason="a", approved_by=None)
    assert "service_fee_reversal" not in await entries(db, order.id)
    await ledger.approve_refund(
        db, order.id, service_fee=20, rider_fee=100, reason="b", approved_by=None
    )
    assert (await entries(db, order.id))["service_fee_reversal"] == 20


@pytest.mark.parametrize(
    "parts",
    [
        {"food": 651},
        {"service_fee": 21},
        {"rider_fee": 101},
        {"excess": 1},  # nothing was overpaid
    ],
)
async def test_refund_cannot_exceed_paid(db, parts):
    _, order = await paid_order(db)
    with pytest.raises(AppError) as e:
        await ledger.approve_refund(db, order.id, reason="x", approved_by=None, **parts)
    assert e.value.code == "refund_exceeds_paid"


async def test_refund_total_limit_across_refunds(db):
    _, order = await paid_order(db)
    await ledger.approve_refund(db, order.id, food=600, reason="a", approved_by=None)
    with pytest.raises(AppError):
        await ledger.approve_refund(db, order.id, food=51, reason="b", approved_by=None)


async def test_overpayment_refund(db):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel)
    await ledger.record_payment(db, order, amount=800)  # 30 over
    await ledger.approve_refund(db, order.id, excess=30, reason="overpaid", approved_by=None)
    e = await entries(db, order.id)
    assert "commission_reversal" not in e and "service_fee_reversal" not in e


async def test_refund_requires_payment(db):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel)
    with pytest.raises(AppError) as e:
        await ledger.approve_refund(db, order.id, food=10, reason="x", approved_by=None)
    assert e.value.code == "not_paid"


async def test_refund_id_makes_approval_idempotent(db):
    _, order = await paid_order(db)
    rid = uuid.uuid4()
    a = await ledger.approve_refund(
        db, order.id, food=100, reason="x", approved_by=None, refund_id=rid
    )
    b = await ledger.approve_refund(
        db, order.id, food=100, reason="x", approved_by=None, refund_id=rid
    )
    assert a.id == b.id == rid
    assert (await entries(db, order.id))["commission_reversal"] == 10


async def test_mark_refund_sent_idempotent_and_conflicting_code(db):
    _, order = await paid_order(db)
    r = await ledger.approve_refund(db, order.id, food=100, reason="x", approved_by=None)
    await ledger.mark_refund_sent(db, r.id, mpesa_code="TK1", sent_by=None)
    await ledger.mark_refund_sent(db, r.id, mpesa_code="tk1", sent_by=None)
    assert (await entries(db, order.id))["refund"] == 100
    with pytest.raises(AppError) as e:
        await ledger.mark_refund_sent(db, r.id, mpesa_code="TK2", sent_by=None)
    assert e.value.code == "already_sent"


# --- Database guards ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE ledger_entries SET amount = amount + 1",
        "DELETE FROM ledger_entries",
        "TRUNCATE ledger_entries CASCADE",
    ],
)
async def test_ledger_is_append_only(db, sql):
    await paid_order(db)
    with pytest.raises(DBAPIError, match="append-only"):
        async with db.begin_nested():
            await db.execute(text(sql))


async def test_negative_amount_rejected(db):
    _, order = await paid_order(db)
    with pytest.raises(ValueError):
        await ledger._write(db, "commission", -5, order_id=order.id)


async def test_balances_are_sums_of_entries(db):
    hotel, order = await paid_order(db)
    await ledger.approve_refund(db, order.id, food=200, reason="x", approved_by=None)
    total_obligations = (
        await db.execute(
            text(
                "SELECT COALESCE(SUM(CASE WHEN from_party='hotel' THEN amount ELSE -amount END),0)"
                " FROM ledger_entries WHERE kind='obligation' AND order_id=:o"
            ),
            {"o": order.id},
        )
    ).scalar_one()
    assert await ledger.owed(db, ("hotel", hotel.id), ("platform", None)) == total_obligations
    assert total_obligations == 85 - 20  # commission 65 + fee 20 - reversal floor(10 % x 200)
