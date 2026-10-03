"""M4 acceptance: every matching case in spec section 14; one code can never confirm two orders;
concurrency; expiry and late payments (D5); review resolution; cash; refunds."""

import asyncio
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from app.core.errors import AppError
from app.core.time import utcnow
from app.models import LedgerEntry, Order, Payment, Refund, ReviewItem
from app.services import jobs, ledger, payments
from tests.factories import auth_header, make_hotel, make_order, make_user

CODE = "SJK3ABC12D"


async def entries(db, order_id) -> dict[str, int]:
    rows = await db.execute(
        select(LedgerEntry.entry_type, func.sum(LedgerEntry.amount))
        .where(LedgerEntry.order_id == order_id)
        .group_by(LedgerEntry.entry_type)
    )
    return {t: int(a) for t, a in rows.all()}


async def reviews(db, order_id=None, type=None) -> list[ReviewItem]:
    stmt = select(ReviewItem)
    if order_id:
        stmt = stmt.where(ReviewItem.order_id == order_id)
    if type:
        stmt = stmt.where(ReviewItem.type == type)
    return list((await db.execute(stmt)).scalars().all())


@pytest.fixture
async def setup(db):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel)  # delivery, option A: Till 770
    cashier = await make_user(db, "cashier", hotel)
    return hotel, order, cashier


async def confirm(db, order, cashier, code=CODE, amount=770, **kw):
    return await payments.confirm_manual(
        db,
        order.id,
        code=code,
        amount=amount,
        paid_at=kw.get("paid_at"),
        cashier_id=cashier.id,
        now=utcnow(),
    )


# --- Manual confirmation: exact / under / over -------------------------------------------------


async def test_exact_amount_confirms_with_ledger(db, setup):
    _, order, cashier = setup
    out = await confirm(db, order, cashier)
    assert (out.result, order.status) == ("paid", "paid")
    assert await entries(db, order.id) == {
        "till_received": 770,
        "commission": 65,
        "service_fee": 20,
    }
    pay = (await db.execute(select(Payment).where(Payment.trans_code == CODE))).scalar_one()
    assert (pay.status, pay.source, pay.confirmed_by) == ("matched", "manual", cashier.id)


async def test_confirm_twice_is_a_noop(db, setup):
    _, order, cashier = setup
    await confirm(db, order, cashier)
    await confirm(db, order, cashier)
    assert (await entries(db, order.id))["till_received"] == 770


async def test_underpaid_holds_then_accept_shortfall(db, setup):
    _, order, cashier = setup
    out = await confirm(db, order, cashier, amount=700)
    assert (out.result, order.status) == ("underpaid", "checking_payment")
    (item,) = await reviews(db, order.id, "underpaid")
    assert await entries(db, order.id) == {}  # nothing accepted yet
    await payments.resolve(db, item, "accept_shortfall", cashier.id, utcnow())
    await db.refresh(order)
    assert order.status == "paid"
    assert (await entries(db, order.id))["till_received"] == 700  # hotel absorbs the KES 70


async def test_underpaid_refund_returns_everything_without_commission(db, setup):
    hotel, order, cashier = setup
    await confirm(db, order, cashier, amount=700)
    (item,) = await reviews(db, order.id, "underpaid")
    await payments.resolve(db, item, "refund", cashier.id, utcnow())
    await db.refresh(order)
    assert order.status == "cancelled"
    refund = (await db.execute(select(Refund).where(Refund.order_id == order.id))).scalar_one()
    assert (refund.amount, refund.excess_amount) == (700, 700)
    await ledger.mark_refund_sent(db, refund.id, mpesa_code="RFD0000001", sent_by=cashier.id)
    e = await entries(db, order.id)
    assert e == {"till_received": 700, "refund": 700}  # no commission on money handed back
    pos = await ledger.hotel_position(db, hotel.id)
    assert (pos.cash_held, pos.owed_to_platform) == (0, 0)


async def test_overpaid_confirms_and_flags_refund_of_difference(db, setup):
    _, order, cashier = setup
    out = await confirm(db, order, cashier, amount=800)
    assert (out.result, order.status) == ("overpaid", "paid")
    (item,) = await reviews(db, order.id, "overpaid")
    await payments.resolve(db, item, "refund_difference", cashier.id, utcnow())
    refund = (await db.execute(select(Refund).where(Refund.order_id == order.id))).scalar_one()
    assert (refund.amount, refund.excess_amount) == (30, 30)
    assert "commission_reversal" not in await entries(db, order.id)


# --- Wrong hotel, old code, reused code --------------------------------------------------------


async def test_wrong_hotel_sms_does_not_confirm(db, setup):
    _, order, _ = setup
    other = await make_hotel(db)
    await payments.submit_customer_code(db, order.id, CODE, utcnow())
    _, outcome = await payments.record_incoming(
        db,
        till_number=other.till_number,
        code=CODE,
        amount=770,
        paid_at=utcnow(),
        source="forwarder",
        now=utcnow(),
    )
    assert outcome is None  # not matched to hotel A's order
    await db.refresh(order)
    assert order.status == "checking_payment"
    assert await reviews(db, type="unmatched_sms")


async def test_cashier_cannot_use_another_tills_payment(db, setup):
    _, order, cashier = setup
    other = await make_hotel(db)
    await payments.record_incoming(
        db,
        till_number=other.till_number,
        code=CODE,
        amount=770,
        paid_at=utcnow(),
        source="forwarder",
        now=utcnow(),
    )
    with pytest.raises(AppError) as e:
        await confirm(db, order, cashier)
    assert e.value.code == "wrong_till"


async def test_old_code_goes_to_review(db, setup):
    _, order, cashier = setup
    out = await confirm(db, order, cashier, paid_at=order.created_at - timedelta(hours=3))
    assert out.result == "too_old"
    assert order.status == "awaiting_payment"


async def test_reused_code_never_confirms_two_orders(db, setup):
    hotel, order, cashier = setup
    second = await make_order(db, hotel)
    await confirm(db, order, cashier)
    with pytest.raises(AppError) as e:
        await confirm(db, second, cashier)
    assert e.value.code == "code_used"
    with pytest.raises(AppError) as e:
        await payments.submit_customer_code(db, second.id, CODE, utcnow())
    assert e.value.code == "code_used"
    assert second.status == "awaiting_payment"


@pytest.mark.parametrize("raw", ["SJK3", "SJK3ABC12D9", "SJK3ABC12!", ""])
async def test_bad_code_format(db, setup, raw):
    _, order, cashier = setup
    with pytest.raises(AppError):
        await confirm(db, order, cashier, code=raw)


# --- Code before SMS / SMS before code -------------------------------------------------------


async def test_code_before_sms(db, setup):
    hotel, order, _ = setup
    out = await payments.submit_customer_code(db, order.id, " sjk3 abc12d ", utcnow())
    assert (out.result, order.status) == ("pending", "checking_payment")
    _, outcome = await payments.record_incoming(
        db,
        till_number=hotel.till_number,
        code=CODE,
        amount=770,
        paid_at=utcnow(),
        source="forwarder",
        now=utcnow(),
    )
    assert outcome.result == "paid"
    await db.refresh(order)
    assert order.status == "paid"


async def test_sms_before_code(db, setup):
    hotel, order, _ = setup
    second = await make_order(db, hotel)  # same amount: SMS alone can't tell them apart
    _, outcome = await payments.record_incoming(
        db,
        till_number=hotel.till_number,
        code=CODE,
        amount=770,
        paid_at=utcnow(),
        source="forwarder",
        now=utcnow(),
    )
    assert outcome is None and order.status == "awaiting_payment"
    out = await payments.submit_customer_code(db, second.id, CODE, utcnow())
    assert out.result == "paid"
    await db.refresh(order)
    assert (second.status, order.status) == ("paid", "awaiting_payment")


async def test_sms_without_code_auto_matches_a_single_candidate(db, setup):
    hotel, order, _ = setup
    _, outcome = await payments.record_incoming(
        db,
        till_number=hotel.till_number,
        code=CODE,
        amount=770,
        paid_at=utcnow(),
        source="forwarder",
        phone_digits=order.customer_phone[-3:],
        now=utcnow(),
    )
    assert outcome.result == "paid"


async def test_sms_repeat_is_harmless(db, setup):
    hotel, order, _ = setup
    for _ in range(3):
        await payments.record_incoming(
            db,
            till_number=hotel.till_number,
            code=CODE,
            amount=770,
            paid_at=utcnow(),
            source="forwarder",
            now=utcnow(),
        )
    assert await db.scalar(select(func.count()).select_from(Payment)) == 1
    assert (await entries(db, order.id))["till_received"] == 770


# --- Expiry and late payment (D5) --------------------------------------------------------------


async def test_expiry_job_skips_checking_payment(db, setup):
    hotel, order, _ = setup
    checking = await make_order(db, hotel)
    await payments.submit_customer_code(db, checking.id, CODE, utcnow())
    await db.execute(update(Order).values(expires_at=utcnow() - timedelta(minutes=1)))
    n = await jobs.expire_unpaid(db, utcnow())
    await db.refresh(order)
    await db.refresh(checking)
    assert n == 1 and (order.status, checking.status) == ("expired", "checking_payment")
    assert await jobs.expire_unpaid(db, utcnow()) == 0  # safe to run twice


async def _expired_order_with_late_payment(db, setup):
    hotel, order, _ = setup
    order.expires_at = utcnow() - timedelta(minutes=5)
    await db.flush()
    await jobs.expire_unpaid(db, utcnow())
    await payments.submit_customer_code(db, order.id, CODE, utcnow())
    _, outcome = await payments.record_incoming(
        db,
        till_number=hotel.till_number,
        code=CODE,
        amount=770,
        paid_at=utcnow(),
        source="forwarder",
        now=utcnow(),
    )
    assert outcome.result == "late"
    (item,) = [i for i in await reviews(db, order.id, "late_payment") if i.payment_id]
    return order, item


async def test_late_payment_reinstate(db, setup):
    _, _, cashier = setup
    order, item = await _expired_order_with_late_payment(db, setup)
    await payments.resolve(db, item, "reinstate", cashier.id, utcnow())
    await db.refresh(order)
    assert order.status == "paid"
    assert (await entries(db, order.id))["commission"] == 65


async def test_late_payment_refund(db, setup):
    _, _, cashier = setup
    order, item = await _expired_order_with_late_payment(db, setup)
    await payments.resolve(db, item, "refund", cashier.id, utcnow())
    await db.refresh(order)
    assert order.status == "cancelled"
    assert "commission" not in await entries(db, order.id)


async def test_no_sms_alert_after_five_minutes(db, setup):
    _, order, _ = setup
    await payments.submit_customer_code(db, order.id, CODE, utcnow())
    assert await jobs.flag_missing_payments(db, utcnow()) == 0
    later = utcnow() + timedelta(minutes=6)  # order history is append-only: move the clock
    assert await jobs.flag_missing_payments(db, later) == 1
    await jobs.flag_missing_payments(db, later)
    assert len(await reviews(db, order.id, "no_sms")) == 1  # one alert, not one per minute


# --- Reversal, cash ----------------------------------------------------------------------------


async def test_reversal_flags_order(db, setup):
    _, order, cashier = setup
    await confirm(db, order, cashier)
    await payments.record_reversal(db, CODE, utcnow())
    (item,) = await reviews(db, order.id, "reversal")
    await payments.resolve(db, item, "cancel_order", cashier.id, utcnow())
    await db.refresh(order)
    assert order.status == "cancelled"


async def test_cash_received(db):
    hotel = await make_hotel(db)
    order = await make_order(
        db, hotel, order_type="pickup", rider_fee_mode="none", payment_method="cash"
    )
    cashier = await make_user(db, "cashier", hotel)
    await payments.cash_received(db, order.id, cashier.id, utcnow())
    await payments.cash_received(db, order.id, cashier.id, utcnow())  # repeat tap
    assert order.status == "paid"
    assert await entries(db, order.id) == {
        "cash_received": 670,
        "commission": 65,
        "service_fee": 20,
    }


# --- Concurrency (real commits) ----------------------------------------------------------------


async def test_concurrent_confirmations_same_code(committed):
    async with committed() as s:
        hotel = await make_hotel(s)
        order = await make_order(s, hotel)
        other = await make_order(s, hotel)
        cashier = await make_user(s, "cashier", hotel)
        await s.commit()

    async def attempt(oid):
        async with committed() as s:
            try:
                await payments.confirm_manual(
                    s, oid, code=CODE, amount=770, paid_at=None, cashier_id=cashier.id, now=utcnow()
                )
                await s.commit()
                return True
            except AppError:
                await s.rollback()
                return False

    results = await asyncio.gather(*(attempt(order.id if i % 2 else other.id) for i in range(20)))
    assert any(results)
    async with committed() as s:
        paid = (await s.execute(select(Order).where(Order.status == "paid"))).scalars().all()
        assert len(paid) == 1  # one code confirmed exactly one order
        assert await s.scalar(select(func.count()).select_from(Payment)) == 1
        tills = await s.scalar(
            select(func.count())
            .select_from(LedgerEntry)
            .where(LedgerEntry.entry_type == "till_received")
        )
        assert tills == 1


# --- API: roles, scoping, customer and admin endpoints -----------------------------------------


async def test_api_flow(client, db):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel)
    cashier = auth_header(await make_user(db, "cashier", hotel))
    admin = auth_header(await make_user(db, "hotel_admin", hotel))
    other_hotel_staff = auth_header(await make_user(db, "cashier", await make_hotel(db)))

    r = await client.post(f"/api/v1/track/{order.tracking_token}/payment-code", json={"code": CODE})
    assert r.status_code == 200 and r.json()["order_status"] == "checking_payment"

    pending = (await client.get("/api/v1/hotel/payments/pending", headers=cashier)).json()
    assert [p["code"] for p in pending] == [order.code]
    assert (
        await client.get("/api/v1/hotel/payments/pending", headers=other_hotel_staff)
    ).json() == []

    bad = await client.post(
        f"/api/v1/hotel/orders/{order.id}/confirm-payment",
        headers=other_hotel_staff,
        json={"code": CODE, "amount": 770},
    )
    assert bad.status_code == 404
    r = await client.post(
        f"/api/v1/hotel/orders/{order.id}/confirm-payment",
        headers=cashier,
        json={"code": CODE, "amount": 800},
    )
    assert r.json()["result"] == "overpaid"

    (item,) = (await client.get("/api/v1/hotel/review-items", headers=cashier)).json()
    assert item["actions"] == ["refund_difference", "dismiss"]
    r = await client.post(
        f"/api/v1/hotel/review-items/{item['id']}/resolve",
        headers=cashier,
        json={"action": "refund_difference"},
    )
    assert r.status_code == 403  # refunds are for the hotel admin
    r = await client.post(
        f"/api/v1/hotel/review-items/{item['id']}/resolve",
        headers=admin,
        json={"action": "refund_difference"},
    )
    assert r.status_code == 200

    (refund,) = (await client.get("/api/v1/hotel/refunds", headers=cashier)).json()
    assert refund["amount"] == 30
    r = await client.post(
        f"/api/v1/hotel/refunds/{refund['id']}/sent",
        headers=cashier,
        json={"mpesa_code": "rfd0000002"},
    )
    assert r.json()["status"] == "sent" and r.json()["mpesa_code"] == "RFD0000002"


async def test_admin_test_payment_simulator(client, db):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel)
    admin = auth_header(await make_user(db, "super_admin"))
    await client.post(f"/api/v1/track/{order.tracking_token}/payment-code", json={"code": CODE})
    r = await client.post(
        "/api/v1/admin/test-payment",
        headers=admin,
        json={"till_number": hotel.till_number, "code": CODE, "amount": 770},
    )
    assert r.json()["result"] == "paid"
    t = (await client.get(f"/api/v1/track/{order.tracking_token}")).json()
    assert t["status"] == "paid"
    count = (await client.get("/api/v1/admin/review-items/count", headers=admin)).json()
    assert count == {"open": 0}


async def test_hotel_admin_approves_item_refund(client, db):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel)
    cashier_user = await make_user(db, "cashier", hotel)
    await confirm(db, order, cashier_user)
    admin = auth_header(await make_user(db, "hotel_admin", hotel))
    rid = str(uuid.uuid4())
    body = {
        "order_id": str(order.id),
        "food": 100,
        "reason": "Missing kachumbari",
        "refund_id": rid,
    }
    r1 = await client.post("/api/v1/hotel/refunds", headers=admin, json=body)
    r2 = await client.post("/api/v1/hotel/refunds", headers=admin, json=body)
    assert r1.status_code == r2.status_code == 201 and r1.json()["id"] == r2.json()["id"] == rid
    cashier = auth_header(cashier_user)
    assert (
        await client.post("/api/v1/hotel/refunds", headers=cashier, json=body)
    ).status_code == 403


async def test_underpaid_order_leaves_the_waiting_list(client, db):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel)
    cashier_user = await make_user(db, "cashier", hotel)
    cashier = auth_header(cashier_user)
    await confirm(db, order, cashier_user, amount=700)
    assert (await client.get("/api/v1/hotel/payments/pending", headers=cashier)).json() == []
    assert len((await client.get("/api/v1/hotel/review-items", headers=cashier)).json()) == 1
