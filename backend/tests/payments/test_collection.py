"""STK collection: request, duplicate callbacks, query fallback, callback route security."""

import pytest
from sqlalchemy import func, select

from app.payments import collection
from app.payments.adapter import CollectStatus
from app.payments.config import PaymentsConfig
from app.payments.fake import FakeProvider
from app.payments.models import OutboxEvent, RawCallback, StkRequest

CFG = PaymentsConfig(
    payments_enabled=True,
    daraja_callback_base="https://x.example",
    daraja_callback_token="tok-abcdefghijklmnopqrstuvwxyz0123456789",
)


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    for m in ("collection", "routes"):
        monkeypatch.setattr(f"app.payments.{m}.get_payments_config", lambda: CFG)


def cb(checkout, code=0, amount=500, receipt="QJK1ABC2DE"):
    body = {
        "MerchantRequestID": "m",
        "CheckoutRequestID": checkout,
        "ResultCode": code,
        "ResultDesc": "ok",
    }
    if code == 0:
        body["CallbackMetadata"] = {
            "Item": [
                {"Name": "Amount", "Value": amount},
                {"Name": "MpesaReceiptNumber", "Value": receipt},
            ]
        }
    return {"Body": {"stkCallback": body}}


async def topics(db):
    return [
        e.topic for e in (await db.scalars(select(OutboxEvent).order_by(OutboxEvent.created_at)))
    ]


async def test_duplicate_callbacks_confirm_once(db):
    p = FakeProvider()
    r = await collection.start_stk(
        db, order_ref="ABC123", phone="254700000001", amount=500, provider=p
    )
    assert r.status == "sent" and p.calls[0]["account_ref"] == "ABC123"
    assert await collection.handle_stk_callback(db, cb(r.checkout_request_id))
    assert not await collection.handle_stk_callback(db, cb(r.checkout_request_id))
    assert (await db.scalar(select(func.count()).select_from(RawCallback))) == 1
    assert (await topics(db)).count("payment.confirmed") == 1
    assert (await db.scalar(select(StkRequest.status))) == "success"


async def test_wrong_amount_goes_to_review(db):
    r = await collection.start_stk(
        db, order_ref="ABC124", phone="254700000001", amount=500, provider=FakeProvider()
    )
    await collection.handle_stk_callback(db, cb(r.checkout_request_id, amount=100))
    assert (await db.scalar(select(StkRequest.status))) == "review"
    assert "payment.confirmed" not in await topics(db)


async def test_rejected_and_cancelled(db):
    p = FakeProvider()
    p.fail_next = "bad shortcode"
    r = await collection.start_stk(
        db, order_ref="ABC125", phone="254700000001", amount=50, provider=p
    )
    assert r.status == "failed"
    r2 = await collection.start_stk(
        db, order_ref="ABC125", phone="254700000001", amount=50, provider=p
    )
    await collection.handle_stk_callback(db, cb(r2.checkout_request_id, code=1032))
    assert (
        r2.status == "cancelled"
        or (await db.scalar(select(StkRequest.status).where(StkRequest.id == r2.id))) == "cancelled"
    )


async def test_no_second_payment_while_one_is_live(db):
    p = FakeProvider()
    await collection.start_stk(db, order_ref="ABC126", phone="254700000001", amount=50, provider=p)
    with pytest.raises(ValueError):
        await collection.start_stk(
            db, order_ref="ABC126", phone="254700000001", amount=50, provider=p
        )


async def test_query_fallback_never_auto_confirms(db):
    p = FakeProvider()
    r = await collection.start_stk(
        db, order_ref="ABC127", phone="254700000001", amount=50, provider=p
    )
    assert not await collection.query_stuck(db, "ABC127", provider=p)  # still pending
    p.statuses[r.checkout_request_id] = CollectStatus(result_code=0)
    assert await collection.query_stuck(db, "ABC127", provider=p)
    assert (await db.scalar(select(StkRequest.status).where(StkRequest.id == r.id))) == "review"


async def test_callback_route_needs_the_secret_token(client):
    url = "/api/v1/payments/daraja/{}/stk"
    assert (await client.post(url.format("wrong"), json=cb("x"))).status_code == 404
    ok = await client.post(url.format(CFG.daraja_callback_token), json=cb("unknown"))
    assert ok.status_code == 200 and ok.json()["ResultCode"] == 0
