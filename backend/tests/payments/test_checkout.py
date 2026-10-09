"""STK checkout: only for hotels switched on, never while in practice mode, pilot flow untouched."""

import uuid

import pytest
from sqlalchemy import func, select

from app import payments
from app.api.v1 import ordering
from app.models import Order, ReviewItem
from app.payments import ledger
from app.payments.config import PaymentsConfig
from app.payments.fake import FakeProvider
from app.payments.models import HotelFlag, StkRequest, WalletEntry
from app.services import order_flow
from tests.factories import auth_header, make_user
from tests.test_delivery import make_rider
from tests.test_ordering import NOW, body, key, open_hotel, set_zone

TOKEN = "tok-abcdefghijklmnopqrstuvwxyz0123456789"


def cfg_for(**kw) -> PaymentsConfig:
    base = dict(
        payments_enabled=True,
        payments_shadow=False,
        payments_stk_checkout=True,
        daraja_callback_base="https://x.example",
        daraja_callback_token=TOKEN,
    )
    return PaymentsConfig(**{**base, **kw})


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(ordering, "utcnow", lambda: NOW)
    provider = FakeProvider()
    monkeypatch.setattr("app.payments.collection.get_provider", lambda: provider)

    def use(cfg: PaymentsConfig):
        for m in ("service", "hook", "collection", "routes", "payouts", "scheduler"):
            monkeypatch.setattr(f"app.payments.{m}.get_payments_config", lambda: cfg, raising=False)
        monkeypatch.setattr("app.api.v1.wallet.get_payments_config", lambda: cfg)

    use(cfg_for())
    return provider, use


async def place(client, db, *, on=True, stk=None):
    stk = on if stk is None else stk
    hotel, product = await open_hotel(db)
    await set_zone(db)
    if on:
        db.add(HotelFlag(hotel_id=hotel.id, stk_enabled=True))
    await db.flush()
    r = await client.post(
        "/api/v1/orders",
        json=body(hotel, product, expected_total=770 if stk else 670),
        headers=key(),
    )
    assert r.status_code == 201, r.text
    return hotel, r.json()


def callback(req: StkRequest, *, amount=None, code=0, receipt=None):
    items = [
        {"Name": "Amount", "Value": amount if amount is not None else req.amount},
        {"Name": "MpesaReceiptNumber", "Value": receipt or "R" + uuid.uuid4().hex[:9].upper()},
    ]
    cb = {"CheckoutRequestID": req.checkout_request_id, "ResultCode": code}
    if code == 0:
        cb["CallbackMetadata"] = {"Item": items}
    return {"Body": {"stkCallback": cb}}


async def stk_of(db, code):
    order = await db.scalar(select(Order).where(Order.code == code))
    return order, await db.scalar(select(StkRequest).where(StkRequest.order_ref == str(order.id)))


async def test_switched_off_the_pilot_flow_is_unchanged(client, db, setup):
    provider, use = setup
    use(cfg_for(payments_enabled=False))
    _, placed = await place(client, db, stk=False)
    assert placed["pay_by_stk"] is False and not provider.calls
    assert await db.scalar(select(func.count()).select_from(StkRequest)) == 0


async def test_practice_mode_never_sends_a_real_prompt(client, db, setup):
    provider, use = setup
    use(cfg_for(payments_shadow=True))
    _, placed = await place(client, db, stk=False)
    assert placed["pay_by_stk"] is False and not provider.calls


async def test_a_hotel_not_switched_on_keeps_the_till_flow(client, db, setup):
    provider, _ = setup
    _, placed = await place(client, db, on=False)
    assert placed["pay_by_stk"] is False and not provider.calls


async def test_checkout_sends_a_prompt_and_the_callback_marks_it_paid(client, db, setup):
    provider, _ = setup
    hotel, placed = await place(client, db)
    assert placed["pay_by_stk"] is True
    order, req = await stk_of(db, placed["code"])
    assert provider.calls[0]["account_ref"] == order.code  # M-Pesa shows the order code
    assert req.amount == order.till_amount and req.status == "sent"
    # rider + hotel + platform parts add up to exactly what the customer is asked to pay
    assert req.rider_fee + req.hotel_share + req.platform_fee == order.till_amount

    url = f"/api/v1/payments/daraja/{TOKEN}/stk"
    assert (await client.post(url, json=callback(req))).status_code == 200
    await db.refresh(order)
    assert order.status == "paid" and order.paid_at is not None
    again = await client.post(url, json=callback(req))  # Daraja repeats itself
    assert again.status_code == 200
    n = await db.scalar(
        select(func.count()).select_from(WalletEntry).where(WalletEntry.kind == "hotel_share_held")
    )
    assert n == 1
    # None of the pilot Till ledger was written: the hotel never received this money.
    from app.models import LedgerEntry

    assert (
        await db.scalar(
            select(func.count()).select_from(LedgerEntry).where(LedgerEntry.order_id == order.id)
        )
        == 0
    )


async def test_wrong_amount_does_not_mark_the_order_paid(client, db, setup):
    _, _ = setup
    _, placed = await place(client, db)
    order, req = await stk_of(db, placed["code"])
    await client.post(f"/api/v1/payments/daraja/{TOKEN}/stk", json=callback(req, amount=10))
    await db.refresh(order)
    assert order.status == "awaiting_payment"


async def test_cancelled_prompt_can_be_sent_again_once(client, db, setup):
    provider, _ = setup
    _, placed = await place(client, db)
    order, req = await stk_of(db, placed["code"])
    pay = f"/api/v1/track/{placed['tracking_token']}/pay"
    assert (await client.post(pay)).status_code == 409  # prompt is still on the phone
    await client.post(f"/api/v1/payments/daraja/{TOKEN}/stk", json=callback(req, code=1032))
    ok = await client.post(pay)
    assert ok.status_code == 200 and ok.json()["sent"] is True
    assert len(provider.calls) == 2
    t = (await client.get(f"/api/v1/track/{placed['tracking_token']}")).json()
    assert t["pay_by_stk"] is True and t["stk_status"] == "sent"


async def test_paid_order_delivered_credits_rider_and_hotel(client, db, setup):
    _, _ = setup
    hotel, placed = await place(client, db)
    order, req = await stk_of(db, placed["code"])
    await client.post(f"/api/v1/payments/daraja/{TOKEN}/stk", json=callback(req))
    await db.refresh(order)
    rider = await make_rider(db)
    order.rider_id = rider.id
    order.status = "on_the_way"
    await db.flush()
    from app.core.time import utcnow
    from app.services import delivery

    await delivery.delivered(
        db, order.id, rider.id, code=order.delivery_code, cash_fee_received=None, now=utcnow()
    )
    assert (await payments.get_balance(db, rider.id))["available"] == order.rider_fee
    assert await ledger.balance(db, "hotel", hotel.id, "available", shadow=False) == req.hotel_share


async def test_rejecting_a_stk_paid_order_releases_holds_and_asks_for_a_refund(client, db, setup):
    _, _ = setup
    hotel, placed = await place(client, db)
    order, req = await stk_of(db, placed["code"])
    await client.post(f"/api/v1/payments/daraja/{TOKEN}/stk", json=callback(req))
    await db.refresh(order)
    admin = await make_user(db, "hotel_admin", hotel)
    from app.core.time import utcnow

    await order_flow.reject(
        db,
        order.id,
        reason_code="sold_out",
        note=None,
        user_id=admin.id,
        hotel_id=hotel.id,
        now=utcnow(),
    )
    total = await db.scalar(
        select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(
            WalletEntry.order_ref == str(order.id)
        )
    )
    assert total == 0  # every hold released
    item = await db.scalar(select(ReviewItem).where(ReviewItem.order_id == order.id))
    assert item is not None and "refund the customer" in item.reason


async def test_admin_can_switch_a_hotel_on_and_off(client, db, setup):
    hotel, _ = await open_hotel(db)
    boss = await make_user(db, "super_admin")
    h = auth_header(boss)
    r = await client.put(
        f"/api/v1/admin/payments/hotels/{hotel.id}", json={"stk_enabled": True}, headers=h
    )
    assert r.status_code == 200 and r.json()["stk_enabled"] is True
    listing = (await client.get("/api/v1/admin/payments/hotels", headers=h)).json()
    assert [x for x in listing["hotels"] if x["id"] == str(hotel.id)][0]["stk_enabled"] is True
    other = await make_user(db, "hotel_admin", hotel)
    denied = await client.put(
        f"/api/v1/admin/payments/hotels/{hotel.id}",
        json={"stk_enabled": False},
        headers=auth_header(other),
    )
    assert denied.status_code == 403
