"""M5 acceptance: a paid order reaches the hotel screen within 3 s; invalid status jumps return
409; D6 acceptance timeout."""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.core.time import utcnow
from app.models import Customer, Hotel, LedgerEntry, Order, Refund
from app.services import events, ledger, order_flow, payments
from tests.factories import auth_header, make_hotel, make_order, make_user

CODE = "SJK3ABC12D"


async def paid_order(db, hotel=None, **kw):
    hotel = hotel or await make_hotel(db)
    order = await make_order(db, hotel, **kw)
    cashier = await make_user(db, "cashier", hotel)
    await payments.confirm_manual(
        db,
        order.id,
        code=kw.pop("code", CODE),
        amount=order.till_amount,
        paid_at=None,
        cashier_id=cashier.id,
        now=utcnow(),
    )
    return hotel, order, cashier


def step(fn, db, order, user, **kw):
    return fn(db, order.id, user_id=user.id, hotel_id=order.hotel_id, now=utcnow(), **kw)


async def test_pickup_flow_and_completed_count(db):
    hotel, order, cashier = await paid_order(db, order_type="pickup", rider_fee_mode="none")
    await step(order_flow.accept, db, order, cashier, prep_minutes=15)
    await step(order_flow.accept, db, order, cashier, prep_minutes=15)  # repeat tap: no-op
    await step(order_flow.preparing, db, order, cashier)
    await step(order_flow.ready, db, order, cashier)
    await step(order_flow.collected, db, order, cashier)
    assert (order.status, order.prep_minutes) == ("collected", 15)
    assert order.accepted_at and order.ready_at and order.collected_at
    assert (await db.get(Customer, order.customer_phone)).completed_orders == 1


@pytest.mark.parametrize(
    ("action", "kw"),
    [(order_flow.ready, {}), (order_flow.preparing, {}), (order_flow.collected, {})],
)
async def test_invalid_jumps_are_409(db, action, kw):
    _, order, cashier = await paid_order(db, order_type="pickup", rider_fee_mode="none")
    with pytest.raises(AppError) as e:
        await step(action, db, order, cashier, **kw)
    assert e.value.status_code == 409


async def test_cannot_accept_unpaid_mpesa_order(db):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel)
    cashier = await make_user(db, "cashier", hotel)
    with pytest.raises(AppError) as e:
        await step(order_flow.accept, db, order, cashier, prep_minutes=10)
    assert e.value.status_code == 409


async def test_delivery_orders_are_not_collected(db):
    _, order, cashier = await paid_order(db)
    for fn, kw in (
        (order_flow.accept, {"prep_minutes": 10}),
        (order_flow.preparing, {}),
        (order_flow.ready, {}),
    ):
        await step(fn, db, order, cashier, **kw)
    with pytest.raises(AppError) as e:
        await step(order_flow.collected, db, order, cashier)
    assert e.value.code == "not_pickup"


async def test_reject_paid_order_records_full_refund(db):
    _, order, cashier = await paid_order(db)
    await step(order_flow.reject, db, order, cashier, reason_code="sold_out", note="No pilau")
    await step(order_flow.reject, db, order, cashier, reason_code="sold_out", note=None)  # repeat
    assert order.status == "rejected" and order.reason == "An item is sold out: No pilau"
    refunds = (await db.execute(select(Refund).where(Refund.order_id == order.id))).scalars().all()
    assert [r.amount for r in refunds] == [770]


async def test_cash_pickup_accepted_directly_and_cash_recorded_at_collection(db):
    hotel = await make_hotel(db)
    order = await make_order(
        db, hotel, order_type="pickup", rider_fee_mode="none", payment_method="cash"
    )
    cashier = await make_user(db, "cashier", hotel)
    for fn, kw in (
        (order_flow.accept, {"prep_minutes": 10}),
        (order_flow.preparing, {}),
        (order_flow.ready, {}),
        (order_flow.collected, {}),
    ):
        await step(fn, db, order, cashier, **kw)
    cash = await db.scalar(
        select(LedgerEntry.amount).where(
            LedgerEntry.order_id == order.id, LedgerEntry.entry_type == "cash_received"
        )
    )
    assert (order.status, cash) == ("collected", 670)


async def test_reject_unpaid_cash_order_has_no_refund(db):
    hotel = await make_hotel(db)
    order = await make_order(
        db, hotel, order_type="pickup", rider_fee_mode="none", payment_method="cash"
    )
    cashier = await make_user(db, "cashier", hotel)
    await step(order_flow.reject, db, order, cashier, reason_code="too_busy", note=None)
    assert await ledger.amount_paid(db, order.id) == 0
    assert (await db.execute(select(Refund).where(Refund.order_id == order.id))).first() is None


# --- D6 ------------------------------------------------------------------------------------------


async def test_auto_reject_after_ten_minutes_and_two_misses_pause(db):
    hotel, first, _ = await paid_order(db)
    second = await make_order(db, hotel)
    cashier = await make_user(db, "cashier", hotel)
    await payments.confirm_manual(
        db,
        second.id,
        code="SJK3ABC12E",
        amount=770,
        paid_at=None,
        cashier_id=cashier.id,
        now=utcnow(),
    )
    now = utcnow()
    assert await order_flow.auto_reject_late(db, now + timedelta(minutes=4)) == 0
    alerts = await order_flow.duty_alerts(db, now + timedelta(minutes=6))
    assert {a["code"] for a in alerts} == {first.code, second.code}

    assert await order_flow.auto_reject_late(db, now + timedelta(minutes=11)) == 2
    await db.refresh(first)
    assert first.status == "rejected" and first.reason == "The hotel didn't respond in time"
    assert (
        await db.execute(select(Refund).where(Refund.order_id == first.id))
    ).scalar_one().amount == 770
    await db.refresh(hotel)
    assert hotel.accepting_orders is False  # two misses in a row


async def test_one_miss_after_an_accept_does_not_pause(db):
    hotel, ok, cashier = await paid_order(db)
    await step(order_flow.accept, db, ok, cashier, prep_minutes=10)
    late = await make_order(db, hotel)
    await payments.confirm_manual(
        db,
        late.id,
        code="SJK3ABC12F",
        amount=770,
        paid_at=None,
        cashier_id=cashier.id,
        now=utcnow(),
    )
    await order_flow.auto_reject_late(db, utcnow() + timedelta(minutes=11))
    await db.refresh(hotel)
    assert hotel.accepting_orders is True


# --- API --------------------------------------------------------------------------------------


async def test_api_board_actions_and_scoping(client, db):
    hotel, order, cashier_user = await paid_order(db, order_type="pickup", rider_fee_mode="none")
    staff = auth_header(cashier_user)
    other = auth_header(await make_user(db, "cashier", await make_hotel(db)))

    board = (await client.get("/api/v1/hotel/orders", headers=staff)).json()
    assert [o["code"] for o in board] == [order.code]
    assert (await client.get("/api/v1/hotel/orders", headers=other)).json() == []
    r = await client.post(
        f"/api/v1/hotel/orders/{order.id}/accept", headers=other, json={"prep_minutes": 10}
    )
    assert r.status_code == 404

    r = await client.post(f"/api/v1/hotel/orders/{order.id}/ready", headers=staff)
    assert r.status_code == 409 and r.json()["error"]["code"] == "wrong_status"
    r = await client.post(
        f"/api/v1/hotel/orders/{order.id}/accept", headers=staff, json={"prep_minutes": 20}
    )
    assert r.json()["status"] == "accepted" and r.json()["prep_minutes"] == 20
    for action in ("preparing", "ready", "collected"):
        r = await client.post(f"/api/v1/hotel/orders/{order.id}/{action}", headers=staff)
        assert r.status_code == 200, r.text
    done = (await client.get("/api/v1/hotel/orders?view=done", headers=staff)).json()
    assert done[0]["status"] == "collected"
    t = (await client.get(f"/api/v1/track/{order.tracking_token}")).json()
    assert t["status"] == "collected" and t["prep_minutes"] == 20


async def test_reject_reason_validation(client, db):
    _, order, cashier = await paid_order(db)
    r = await client.post(
        f"/api/v1/hotel/orders/{order.id}/reject",
        headers=auth_header(cashier),
        json={"reason": "bored"},
    )
    assert r.status_code == 422


# --- Live updates: the paid order reaches the hotel screen within 3 seconds -------------------


async def test_paid_order_reaches_hotel_channel_within_3s(committed):
    async with committed() as s:
        hotel = await make_hotel(s)
        order = await make_order(s, hotel)
        cashier = await make_user(s, "cashier", hotel)
        await s.commit()

    stream = events.stream(f"hotel:{hotel.id}")
    assert (await anext(stream)).startswith(": connected")
    nxt = asyncio.ensure_future(anext(stream))

    async with committed() as s:
        await payments.confirm_manual(
            s, order.id, code=CODE, amount=770, paid_at=None, cashier_id=cashier.id, now=utcnow()
        )
        assert not nxt.done()  # nothing is sent before the commit
        await s.commit()

    msg = await asyncio.wait_for(nxt, timeout=3)
    assert '"status": "paid"' in msg and order.code in msg and '"new_paid": true' in msg
    await stream.aclose()


async def test_rolled_back_change_sends_nothing(committed):
    async with committed() as s:
        hotel = await make_hotel(s)
        order = await make_order(s, hotel)
        cashier = await make_user(s, "cashier", hotel)
        await s.commit()
    stream = events.stream(f"hotel:{hotel.id}")
    await anext(stream)
    nxt = asyncio.ensure_future(anext(stream))
    async with committed() as s:
        await payments.confirm_manual(
            s, order.id, code=CODE, amount=770, paid_at=None, cashier_id=cashier.id, now=utcnow()
        )
        await s.rollback()
    await asyncio.sleep(0.3)
    assert not nxt.done()
    nxt.cancel()
    with pytest.raises(asyncio.CancelledError):
        await nxt
    await stream.aclose()
    async with committed() as s:
        assert (await s.get(Order, order.id)).status == "awaiting_payment"
        assert (await s.get(Hotel, hotel.id)).accepting_orders is True


async def test_auto_reject_refunds_only_what_was_received(db):
    """Regression: an order accepted with a shortfall (KES 700 of 770) must refund 700."""
    hotel = await make_hotel(db)
    short = await make_order(db, hotel)
    normal = await make_order(db, hotel)
    cashier = await make_user(db, "cashier", hotel)
    await payments.confirm_manual(
        db,
        short.id,
        code="SJK3SHORT1",
        amount=700,
        paid_at=None,
        cashier_id=cashier.id,
        now=utcnow(),
    )
    from app.models import ReviewItem

    item = (
        await db.execute(select(ReviewItem).where(ReviewItem.order_id == short.id))
    ).scalar_one()
    await payments.resolve(db, item, "accept_shortfall", cashier.id, utcnow())
    await payments.confirm_manual(
        db,
        normal.id,
        code="SJK3NORML1",
        amount=770,
        paid_at=None,
        cashier_id=cashier.id,
        now=utcnow(),
    )
    assert await order_flow.auto_reject_late(db, utcnow() + timedelta(minutes=11)) == 2
    amounts = {r.order_id: r.amount for r in (await db.execute(select(Refund))).scalars().all()}
    assert amounts == {short.id: 700, normal.id: 770}
