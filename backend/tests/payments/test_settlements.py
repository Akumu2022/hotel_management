"""Money split on payment, released on delivery/hand-over, paid to hotels once a day."""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app import payments
from app.payments import collection, ledger, payouts, scheduler, settlements
from app.payments.config import PaymentsConfig
from app.payments.fake import FakeProvider
from app.payments.models import HotelSettlement, WalletEntry
from app.payments.service import confirm_handover
from tests.factories import make_hotel
from tests.test_delivery import make_rider

NAIROBI = ZoneInfo("Africa/Nairobi")
STK = FakeProvider()  # one instance: its checkout ids keep counting up
PAYEE = ("phone", "254711000001", "H")

CFG = PaymentsConfig(
    payments_enabled=True,
    payments_shadow=False,
    daraja_callback_base="https://x.example",
    daraja_callback_token="tok-abcdefghijklmnopqrstuvwxyz0123456789",
)


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    for m in ("service", "hook", "collection", "routes", "payouts", "scheduler", "settlements"):
        monkeypatch.setattr(f"app.payments.{m}.get_payments_config", lambda: CFG, raising=False)


def next_morning() -> datetime:
    """06:30 tomorrow: after every credit the tests make with the real clock."""
    return datetime.now(NAIROBI).replace(hour=6, minute=30) + timedelta(days=1)


async def pay_order(db, ref, *, hotel_id, rider_fee=100, hotel_share=500, fee=60):
    """A customer pays through STK: the money is held in three parts."""
    req = await collection.start_stk(
        db,
        order_ref=ref,
        phone="254700000001",
        amount=rider_fee + hotel_share + fee,
        rider_fee=rider_fee,
        hotel_id=hotel_id,
        hotel_share=hotel_share,
        platform_fee=fee,
        provider=STK,
    )
    receipt = "R" + uuid.uuid4().hex[:9].upper()
    items = [
        {"Name": "Amount", "Value": rider_fee + hotel_share + fee},
        {"Name": "MpesaReceiptNumber", "Value": receipt},
    ]
    await collection.handle_stk_callback(
        db,
        {
            "Body": {
                "stkCallback": {
                    "CheckoutRequestID": req.checkout_request_id,
                    "ResultCode": 0,
                    "CallbackMetadata": {"Item": items},
                }
            }
        },
    )


async def total(db, ref):
    """Everything the ledger holds for an order, across all parties and buckets."""
    q = select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(WalletEntry.order_ref == ref)
    return int(await db.scalar(q))


async def done(db, ref, hotel, rider, **kw):
    await pay_order(db, ref, hotel_id=hotel.id, **kw)
    await payments.confirm_delivery(db, ref, rider.id, kw.get("rider_fee", 100), hotel_id=hotel.id)


async def test_payment_is_held_in_three_parts_and_sums_to_what_was_paid(db):
    hotel = await make_hotel(db)
    await pay_order(db, "O1", hotel_id=hotel.id)
    assert await total(db, "O1") == 660
    assert await ledger.balance(db, "hotel", hotel.id, "pending", shadow=False) == 500
    assert await ledger.balance(db, "platform", None, "pending", shadow=False) == 160


async def test_delivery_pays_rider_hotel_and_platform_and_still_sums(db):
    hotel, rider = await make_hotel(db), await make_rider(db)
    await pay_order(db, "O2", hotel_id=hotel.id)
    assert await payments.confirm_delivery(db, "O2", rider.id, 100, hotel_id=hotel.id) == 100
    assert (await payments.get_balance(db, rider.id))["available"] == 100
    assert await ledger.balance(db, "hotel", hotel.id, "available", shadow=False) == 500
    assert await ledger.balance(db, "platform", None, "earned", shadow=False) == 60
    assert await ledger.balance(db, "platform", None, "pending", shadow=False) == 0
    assert await total(db, "O2") == 660  # every shilling accounted for
    # The same delivery again changes nothing.
    assert await payments.confirm_delivery(db, "O2", rider.id, 100, hotel_id=hotel.id) == 0
    assert await total(db, "O2") == 660


async def test_pickup_handover_pays_hotel_and_platform_only(db):
    hotel = await make_hotel(db)
    await pay_order(db, "O3", hotel_id=hotel.id, rider_fee=0)
    assert await confirm_handover(db, "O3", hotel_id=hotel.id) == 500
    assert await ledger.balance(db, "hotel", hotel.id, "available", shadow=False) == 500
    assert await confirm_handover(db, "O3", hotel_id=hotel.id) == 0


async def test_rejected_order_moves_every_hold_to_the_customer(db):
    hotel = await make_hotel(db)
    ref = str(uuid.uuid4())
    await pay_order(db, ref, hotel_id=hotel.id)
    assert await payments.reverse(db, ref) == 660
    assert await total(db, ref) == 660  # still held, now as the customer refund
    assert await ledger.balance(db, "customer", uuid.UUID(ref), "reserved", shadow=False) == 660
    assert await ledger.balance(db, "hotel", hotel.id, "pending", shadow=False) == 0
    assert await ledger.balance(db, "platform", None, "pending", shadow=False) == 0


async def test_daily_settlement_pays_once_itemised(db):
    hotel, rider = await make_hotel(db), await make_rider(db)
    await done(db, "O5", hotel, rider)
    await done(db, "O6", hotel, rider, hotel_share=300)
    p = FakeProvider()
    out = await scheduler.daily_hotel_settlement(db, next_morning(), {hotel.id: PAYEE}, p)
    again = await scheduler.daily_hotel_settlement(db, next_morning(), {hotel.id: PAYEE}, p)
    assert out["paid"] == 1 and again.get("already_ran")
    assert len(p.disbursed) == 1 and p.disbursed[0]["amount"] == 800
    s = await db.scalar(select(HotelSettlement))
    assert sorted(i["order_ref"] for i in s.detail) == ["O5", "O6"]
    assert await ledger.balance(db, "hotel", hotel.id, "reserved", shadow=False) == 800


async def test_settlement_result_pays_and_duplicate_is_ignored(db):
    hotel, rider = await make_hotel(db), await make_rider(db)
    await done(db, "O7", hotel, rider)
    p = FakeProvider()
    morning = next_morning()
    await scheduler.daily_hotel_settlement(db, morning, {hotel.id: PAYEE}, p)
    s = await db.scalar(select(HotelSettlement))
    body = {
        "Result": {
            "OriginatorConversationID": str(s.id),
            "ConversationID": "AG9",
            "ResultCode": 0,
            "ResultDesc": "ok",
            "TransactionID": "HKJ12345AB",
            "ResultType": 0,
            "ResultParameters": {"ResultParameter": [{"Key": "TransactionAmount", "Value": 500}]},
        }
    }
    assert await payouts.handle_result(db, body)
    assert not await payouts.handle_result(db, body)
    assert await ledger.balance(db, "hotel", hotel.id, "paid", shadow=False) == 500
    # Tomorrow there is nothing new: the same orders are never paid twice.
    out = await scheduler.daily_hotel_settlement(
        db, morning + timedelta(days=1), {hotel.id: PAYEE}, p
    )
    assert out["paid"] == 0 and len(p.disbursed) == 1


async def test_todays_orders_wait_for_tomorrow(db):
    hotel, rider = await make_hotel(db), await make_rider(db)
    await done(db, "O8", hotel, rider)
    p = FakeProvider()
    this_morning = datetime.now(NAIROBI).replace(hour=0, minute=1)  # before the order was done
    out = await scheduler.daily_hotel_settlement(db, this_morning, {hotel.id: PAYEE}, p)
    assert out["paid"] == 0 and not p.disbursed


async def test_settlement_timeout_is_unknown_and_never_resent(db):
    hotel, rider = await make_hotel(db), await make_rider(db)
    await done(db, "O9", hotel, rider)
    p = FakeProvider()
    p.disburse_error = TimeoutError("net")
    await scheduler.daily_hotel_settlement(db, next_morning(), {hotel.id: PAYEE}, p)
    s = await db.scalar(select(HotelSettlement))
    assert s.status == "unknown"
    assert await settlements.submit(db, s.id, p) == "not_claimed"
    assert len(p.disbursed) == 1
    assert await ledger.balance(db, "hotel", hotel.id, "reserved", shadow=False) == 500


async def test_till_channel_uses_b2b(db):
    hotel, rider = await make_hotel(db), await make_rider(db)
    await done(db, "O10", hotel, rider)
    p = FakeProvider()
    payee = ("till", "123456", "H")
    await scheduler.daily_hotel_settlement(db, next_morning(), {hotel.id: payee}, p)
    assert p.disbursed[0]["till"] == "123456" and p.disbursed[0]["amount"] == 500


async def test_float_check_covers_hotel_money_too(db):
    hotel, rider = await make_hotel(db), await make_rider(db)
    await done(db, "O11", hotel, rider)
    p = FakeProvider()
    p.balance = 100  # it owes the rider 100 and the hotel 500
    out = await scheduler.daily_hotel_settlement(db, next_morning(), {hotel.id: PAYEE}, p)
    assert out["blocked"] and not p.disbursed


async def test_hotel_sees_its_settlements_itemised(client, db, monkeypatch):
    from app.models import Order
    from tests.factories import auth_header, make_order, make_user

    monkeypatch.setattr("app.api.v1.wallet.get_payments_config", lambda: CFG)
    hotel, rider = await make_hotel(db), await make_rider(db)
    order = await make_order(db, hotel, status="delivered")
    admin = await make_user(db, "hotel_admin", hotel)
    ref = str(order.id)
    await pay_order(db, ref, hotel_id=hotel.id)
    await payments.confirm_delivery(db, ref, rider.id, 100, hotel_id=hotel.id)
    await scheduler.daily_hotel_settlement(db, next_morning(), {hotel.id: PAYEE}, FakeProvider())
    j = (await client.get("/api/v1/hotel/settlements", headers=auth_header(admin))).json()
    assert j["enabled"] and j["settlements"][0]["amount"] == 500
    assert j["settlements"][0]["orders"] == [{"code": order.code, "amount": 500}]
    assert j["settlements"][0]["to"] == "0001"
    # Another hotel sees none of it.
    other = await make_user(db, "hotel_admin", await make_hotel(db))
    k = (await client.get("/api/v1/hotel/settlements", headers=auth_header(other))).json()
    assert k["settlements"] == []
    assert isinstance(order, Order)
