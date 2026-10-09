"""Customer refunds: sent once, never lost, retried, never past what was paid."""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app import payments
from app.payments import collection, ledger, payouts, refunds, scheduler
from app.payments.adapter import DisburseStatus, ProviderError
from app.payments.config import PaymentsConfig
from app.payments.fake import FakeProvider
from app.payments.models import CustomerRefund
from tests.factories import make_hotel

NAIROBI = ZoneInfo("Africa/Nairobi")
NOW = datetime.now(NAIROBI)  # the code stamps rows with the real clock
STK = FakeProvider()

CFG = PaymentsConfig(
    payments_enabled=True,
    payments_shadow=False,
    daraja_callback_base="https://x.example",
    daraja_callback_token="tok-abcdefghijklmnopqrstuvwxyz0123456789",
)


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    for m in ("service", "hook", "collection", "routes", "payouts", "scheduler", "refunds"):
        monkeypatch.setattr(f"app.payments.{m}.get_payments_config", lambda: CFG, raising=False)


async def paid_then_reversed(db):
    """An order paid by STK (660) and then rejected: the customer is owed it all back."""
    hotel = await make_hotel(db)
    ref = str(uuid.uuid4())
    req = await collection.start_stk(
        db,
        order_ref=ref,
        phone="254700000001",
        amount=660,
        rider_fee=100,
        hotel_id=hotel.id,
        hotel_share=500,
        platform_fee=60,
        provider=STK,
    )
    items = [
        {"Name": "Amount", "Value": 660},
        {"Name": "MpesaReceiptNumber", "Value": "R" + uuid.uuid4().hex[:9].upper()},
    ]
    cb = {
        "CheckoutRequestID": req.checkout_request_id,
        "ResultCode": 0,
        "CallbackMetadata": {"Item": items},
    }
    await collection.handle_stk_callback(db, {"Body": {"stkCallback": cb}})
    owed = await payments.reverse(db, ref)
    assert owed == 660
    row = await refunds.queue_refund(
        db, order_ref=ref, phone="254700000001", amount=owed, reason="rejected"
    )
    return ref, row


async def balances(db, ref):
    oid = uuid.UUID(ref)
    return {
        b: await ledger.balance(db, "customer", oid, b, shadow=False) for b in ("reserved", "paid")
    }


def result_body(row, amount=660):
    return {
        "Result": {
            "OriginatorConversationID": str(row.id),
            "ConversationID": "AGR1",
            "ResultCode": 0,
            "ResultDesc": "ok",
            "TransactionID": "RFD12345AB",
            "ResultType": 0,
            "ResultParameters": {
                "ResultParameter": [{"Key": "TransactionAmount", "Value": amount}]
            },
        }
    }


async def test_refund_is_sent_once_and_paid_on_success(db):
    ref, row = await paid_then_reversed(db)
    p = FakeProvider()
    await refunds.process(db, NOW, p)
    await refunds.process(db, NOW, p)  # the scheduler runs every minute
    assert len(p.disbursed) == 1
    assert p.disbursed[0]["amount"] == 660 and p.disbursed[0]["phone"] == "254700000001"
    assert await payouts.handle_result(db, result_body(row))
    assert not await payouts.handle_result(db, result_body(row))  # duplicate callback
    assert await balances(db, ref) == {"reserved": 0, "paid": 660}


async def test_a_different_amount_in_the_result_goes_to_a_person(db):
    ref, row = await paid_then_reversed(db)
    await refunds.process(db, NOW, FakeProvider())
    await payouts.handle_result(db, result_body(row, amount=100))
    await db.flush()
    await db.refresh(row)
    assert row.status == "manual_review" and (await balances(db, ref))["reserved"] == 660


async def test_one_live_refund_per_order(db):
    ref, row = await paid_then_reversed(db)
    again = await refunds.queue_refund(
        db, order_ref=ref, phone="254700000001", amount=660, reason="x"
    )
    assert again is None


async def test_timeout_is_unknown_never_resent_then_settled_by_query(db):
    ref, row = await paid_then_reversed(db)
    p = FakeProvider()
    p.disburse_error = TimeoutError("net")
    await refunds.process(db, NOW, p)
    await db.refresh(row)
    assert row.status == "unknown"
    await refunds.process(db, NOW, p)
    assert len(p.disbursed) == 1  # never sent again
    p.disburse_statuses[str(row.id)] = DisburseStatus(0, "ok", "RFD99999ZZ")
    await refunds.process(db, NOW, p)
    assert (await balances(db, ref))["paid"] == 660 and len(p.disbursed) == 1


async def test_failed_refund_keeps_the_money_reserved_and_retries_later(db):
    ref, row = await paid_then_reversed(db)
    p = FakeProvider()
    p.disburse_error = ProviderError("invalid number")
    await refunds.process(db, NOW, p)
    await db.refresh(row)
    assert row.status == "failed" and (await balances(db, ref))["reserved"] == 660
    await refunds.process(db, NOW, p)  # too soon for another attempt
    assert await db.scalar(select(func.count()).select_from(CustomerRefund)) == 1
    later = NOW + timedelta(minutes=20)
    await refunds.process(db, later, p)
    rows = (await db.scalars(select(CustomerRefund).order_by(CustomerRefund.attempt))).all()
    assert [r.attempt for r in rows] == [1, 2] and rows[1].retry_of == row.id


async def test_float_check_counts_what_is_owed_to_customers(db):
    await paid_then_reversed(db)
    assert await scheduler.owed(db, shadow=False) == 660


async def test_no_phone_means_no_automatic_refund(db):
    row = await refunds.queue_refund(
        db, order_ref=str(uuid.uuid4()), phone="", amount=100, reason="x"
    )
    assert row is None
