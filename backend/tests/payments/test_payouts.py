"""B2C payouts: never twice, never lost, never past the float."""

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from app import payments
from app.payments import payouts, scheduler
from app.payments.adapter import DisburseStatus, ProviderError
from app.payments.config import PaymentsConfig
from app.payments.fake import FakeProvider
from app.payments.models import OutboxEvent, Payout
from tests.test_delivery import make_rider

NAIROBI = ZoneInfo("Africa/Nairobi")
NIGHT = datetime(2026, 10, 10, 21, 45, tzinfo=NAIROBI)

CFG = PaymentsConfig(
    payments_enabled=True,
    payments_shadow=False,
    daraja_callback_base="https://x.example",
    daraja_callback_token="tok-abcdefghijklmnopqrstuvwxyz0123456789",
)


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    for m in ("service", "hook", "collection", "routes", "payouts", "scheduler"):
        monkeypatch.setattr(f"app.payments.{m}.get_payments_config", lambda: CFG, raising=False)
    monkeypatch.setattr("app.api.v1.wallet.get_payments_config", lambda: CFG)


async def fund(db, rider, amount, ref=None):
    ref = ref or uuid.uuid4().hex[:8]
    await payments.request_collection(db, ref, amount)
    assert await payments.confirm_delivery(db, ref, rider.id, amount) == amount


async def status_of(db, payout_id):
    return await db.scalar(select(Payout.status).where(Payout.id == payout_id))


async def test_daily_payout_pays_once_even_if_run_twice(db):
    rider = await make_rider(db)
    await fund(db, rider, 300)
    p = FakeProvider()
    payees = {rider.id: "254700000001"}
    first = await scheduler.daily_rider_payout(db, NIGHT, payees, p)
    again = await scheduler.daily_rider_payout(db, NIGHT, payees, p)
    assert first["paid"] == 1 and again.get("already_ran")
    assert len(p.disbursed) == 1  # sent once
    assert await db.scalar(select(func.count()).select_from(Payout)) == 1


async def test_same_rider_cannot_get_two_payouts_in_a_day(db):
    rider = await make_rider(db)
    await fund(db, rider, 300)
    day = NIGHT.date()
    a = await payouts.queue_payout(
        db, rider_id=rider.id, phone="2547", amount=100, kind="auto", day=day
    )
    b = await payouts.queue_payout(
        db, rider_id=rider.id, phone="2547", amount=100, kind="auto", day=day
    )
    assert a is not None and b is None
    assert (await payments.get_balance(db, rider.id))[
        "reserved"
    ] == 100  # the failed 2nd left no trace


async def test_success_moves_reserved_to_paid(db):
    rider = await make_rider(db)
    await fund(db, rider, 300)
    p = FakeProvider()
    await scheduler.daily_rider_payout(db, NIGHT, {rider.id: "254700000001"}, p)
    row = await db.scalar(select(Payout))
    assert row.status == "submitted" and p.disbursed[0]["amount"] == 300
    body = {
        "Result": {
            "OriginatorConversationID": str(row.id),
            "ConversationID": "AG1",
            "ResultCode": 0,
            "ResultDesc": "ok",
            "TransactionID": "SJK12345AB",
            "ResultType": 0,
            "ResultParameters": {"ResultParameter": [{"Key": "TransactionAmount", "Value": 300}]},
        }
    }
    assert await payouts.handle_result(db, body)
    assert not await payouts.handle_result(db, body)  # duplicate callback: once
    bal = await payments.get_balance(db, rider.id)
    assert bal == {"pending": 0, "available": 0, "reserved": 0, "paid": 300}
    await db.refresh(row)
    assert row.status == "succeeded" and row.transaction_id == "SJK12345AB"


async def test_clear_failure_returns_money_to_available(db):
    rider = await make_rider(db)
    await fund(db, rider, 300)
    p = FakeProvider()
    p.disburse_error = ProviderError("invalid number")
    await scheduler.daily_rider_payout(db, NIGHT, {rider.id: "254700000001"}, p)
    row = await db.scalar(select(Payout))
    assert row.status == "failed"
    assert (await payments.get_balance(db, rider.id))["available"] == 300


async def test_timeout_is_unknown_never_resent_and_resolved_by_query(db):
    rider = await make_rider(db)
    await fund(db, rider, 300)
    p = FakeProvider()
    p.disburse_error = TimeoutError("network")
    await scheduler.daily_rider_payout(db, NIGHT, {rider.id: "254700000001"}, p)
    row = await db.scalar(select(Payout))
    assert row.status == "unknown"
    assert (await payments.get_balance(db, rider.id))["reserved"] == 300  # still held
    # Submitting again does nothing: the row is no longer queued.
    assert await payouts.submit(db, row.id, p) == "not_claimed"
    assert len(p.disbursed) == 1  # exactly one attempt ever reached the provider
    # Still no answer: stays unknown.
    assert await payouts.resolve_unknown(db, NIGHT, p) == 0
    # Daraja says it worked.
    p.disburse_statuses[str(row.id)] = DisburseStatus(0, "ok", "SJK99999ZZ")
    assert await payouts.resolve_unknown(db, NIGHT, p) == 1
    assert (await payments.get_balance(db, rider.id))["paid"] == 300
    assert len(p.disbursed) == 1


async def test_unknown_after_a_day_goes_to_manual_review(db):
    rider = await make_rider(db)
    await fund(db, rider, 300)
    p = FakeProvider()
    p.disburse_error = TimeoutError("network")
    await scheduler.daily_rider_payout(db, NIGHT, {rider.id: "254700000001"}, p)
    later = datetime(2026, 10, 12, 9, 0, tzinfo=NAIROBI)
    await payouts.resolve_unknown(db, later, p)
    row = await db.scalar(select(Payout))
    assert row.status == "manual_review"
    assert (await payments.get_balance(db, rider.id))["reserved"] == 300  # never auto-released


async def test_float_check_blocks_payouts(db):
    rider = await make_rider(db)
    await fund(db, rider, 300)
    p = FakeProvider()
    p.balance = 100  # owes 300, holds 100
    out = await scheduler.daily_rider_payout(db, NIGHT, {rider.id: "254700000001"}, p)
    assert out["blocked"] and not p.disbursed
    assert (await payments.get_balance(db, rider.id))["available"] == 300
    topics = [e.topic for e in await db.scalars(select(OutboxEvent))]
    assert "float.low" in topics
    # Fixed: the same day can still run afterwards (a blocked run is not "done").
    p.balance = 1000
    # Inside the same quarter hour it is not retried (Daraja is not asked every minute)...
    same = await scheduler.daily_rider_payout(db, NIGHT, {rider.id: "254700000001"}, p)
    assert same.get("already_ran") and not p.disbursed
    # ...but a quarter of an hour later it is.
    later = NIGHT + timedelta(minutes=16)
    out2 = await scheduler.daily_rider_payout(db, later, {rider.id: "254700000001"}, p)
    assert out2["paid"] == 1


async def test_unreadable_balance_fails_closed(db):
    rider = await make_rider(db)
    await fund(db, rider, 300)

    class NoBalance(FakeProvider):
        async def account_balance(self):
            raise ProviderError("not wired")

    p = NoBalance()
    out = await scheduler.daily_rider_payout(db, NIGHT, {rider.id: "254700000001"}, p)
    assert out["blocked"] and not p.disbursed


async def test_below_minimum_rolls_over_and_caps_apply(db):
    small, big = await make_rider(db), await make_rider(db)
    await fund(db, small, 20)
    await fund(db, big, 400)
    p = FakeProvider()
    out = await scheduler.daily_rider_payout(
        db, NIGHT, {small.id: "254700000001", big.id: "254700000002"}, p
    )
    assert out["paid"] == 1 and out["skipped"] == 1
    assert (await payments.get_balance(db, small.id))["available"] == 20


async def test_withdraw_free_then_charged_and_idempotent(db, monkeypatch):
    rider = await make_rider(db)
    await fund(db, rider, 500)
    p = FakeProvider()
    kw = {"phone": "254700000001", "now": NIGHT, "provider": p}
    w1 = await payouts.request_withdrawal(db, rider.id, idem_key="k1", accept_charge=False, **kw)
    assert w1.kind == "withdraw" and w1.amount == 500 and w1.charge == 0
    again = await payouts.request_withdrawal(db, rider.id, idem_key="k1", accept_charge=False, **kw)
    assert again.id == w1.id and len(p.disbursed) == 1  # same tap twice = one payout
    await fund(db, rider, 200)
    later = {**kw, "now": datetime(2026, 10, 10, 21, 50, tzinfo=NAIROBI)}
    monkeypatch.setattr(payouts, "WITHDRAW_COOLDOWN", payouts.timedelta(0))
    with pytest.raises(payouts.PayoutError) as e:
        await payouts.request_withdrawal(db, rider.id, idem_key="k2", accept_charge=False, **later)
    assert e.value.code == "charge_needed" and e.value.extra["charge"] == 30


async def test_withdraw_extra_takes_the_charge(db, monkeypatch):
    rider = await make_rider(db)
    await fund(db, rider, 500)
    p = FakeProvider()
    kw = {"phone": "254700000001", "provider": p}
    await payouts.request_withdrawal(
        db, rider.id, idem_key="a", accept_charge=False, now=NIGHT, **kw
    )
    await fund(db, rider, 200)
    monkeypatch.setattr(payouts, "WITHDRAW_COOLDOWN", payouts.timedelta(0))
    w = await payouts.request_withdrawal(
        db,
        rider.id,
        idem_key="b",
        accept_charge=True,
        now=datetime(2026, 10, 10, 22, 0, tzinfo=NAIROBI),
        **kw,
    )
    assert w.kind == "withdraw_extra" and w.charge == 30 and w.amount == 170
    assert p.disbursed[-1]["amount"] == 170
    assert (await payments.get_balance(db, rider.id))["available"] == 0


async def test_withdraw_below_minimum_refused(db):
    rider = await make_rider(db)
    await fund(db, rider, 20)
    with pytest.raises(payouts.PayoutError) as e:
        await payouts.request_withdrawal(
            db,
            rider.id,
            phone="254700000001",
            idem_key="z",
            accept_charge=False,
            now=NIGHT,
            provider=FakeProvider(),
        )
    assert e.value.code == "below_minimum"


async def test_submit_marks_submitted_before_calling_the_provider(db):
    """A crash mid-call must leave 'submitted' (maybe sent), never 'queued' (would be resent)."""
    rider = await make_rider(db)
    await fund(db, rider, 300)
    row = await payouts.queue_payout(
        db, rider_id=rider.id, phone="254700000001", amount=300, kind="auto", day=NIGHT.date()
    )
    seen = {}

    class Spy(FakeProvider):
        async def disburse(self, **kw):
            seen["status"] = await db.scalar(select(Payout.status).where(Payout.id == row.id))
            return await super().disburse(**kw)

    await payouts.submit(db, row.id, Spy())
    assert seen["status"] == "submitted"


async def test_withdraw_endpoint_needs_password_and_key(client, db):
    from tests.factories import auth_header

    rider = await make_rider(db)
    await fund(db, rider, 500)
    h = auth_header(rider)
    url = "/api/v1/rider/wallet/withdraw"
    no_key = await client.post(url, json={"password": "x"}, headers=h)
    assert no_key.status_code == 400
    wrong = await client.post(
        url, json={"password": "not-it"}, headers={**h, "Idempotency-Key": "abcdefgh12"}
    )
    assert wrong.status_code == 403 and wrong.json()["error"]["code"] == "wrong_password"
    assert (await payments.get_balance(db, rider.id))["available"] == 500  # nothing moved


async def test_job_does_nothing_when_payments_are_off(db, monkeypatch):
    off = PaymentsConfig(payments_enabled=False)
    monkeypatch.setattr("app.payments.scheduler.get_payments_config", lambda: off)
    assert await scheduler.run(db, NIGHT) == 0
