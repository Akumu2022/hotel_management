"""Payments module: instant credit, idempotency, flag-off no-op, append-only ledger."""

import pytest
from sqlalchemy import select, text

from app import payments
from app.core.time import utcnow
from app.payments import ledger
from app.payments.config import PaymentsConfig
from app.payments.models import OutboxEvent
from app.services import delivery  # noqa: F401  (old module still importable)
from tests.factories import make_hotel, make_order
from tests.test_delivery import make_rider


@pytest.fixture
def flag(monkeypatch):
    def _set(enabled=True, shadow=False):
        cfg = PaymentsConfig(payments_enabled=enabled, payments_shadow=shadow)
        monkeypatch.setattr("app.payments.config.get_payments_config", lambda: cfg)
        monkeypatch.setattr("app.payments.service.get_payments_config", lambda: cfg)
        monkeypatch.setattr("app.payments.hook.get_payments_config", lambda: cfg)

    return _set


async def test_credit_is_idempotent_and_never_negative(db, flag):
    flag()
    rider = await make_rider(db)
    assert await payments.request_collection(db, "ORD1", rider.id, 150)
    assert await payments.confirm_delivery(db, "ORD1", rider.id, 150) == 150
    assert await payments.confirm_delivery(db, "ORD1", rider.id, 150) == 0  # retry: no 2nd credit
    bal = await payments.get_balance(db, rider.id)
    assert bal == {"pending": 0, "available": 150, "reserved": 0, "paid": 0}
    with pytest.raises(ledger.InsufficientFunds):
        await ledger.move(
            db,
            idem_key="x",
            party_type="rider",
            party_id=rider.id,
            src="available",
            dst="reserved",
            amount=151,
            kind="t",
            order_ref=None,
            shadow=False,
        )
    events = (await db.scalars(select(OutboxEvent))).all()
    assert [e.topic for e in events] == ["wallet.credited"]


async def test_order_not_paid_through_module_is_ignored_unless_shadow(db, flag):
    rider = await make_rider(db)
    flag(shadow=False)
    assert await payments.confirm_delivery(db, "OLD1", rider.id, 100) == 0
    flag(shadow=True)
    assert await payments.confirm_delivery(db, "OLD2", rider.id, 100) == 100
    assert (await payments.get_balance(db, rider.id))["available"] == 100  # shadow balance


async def test_reverse_pending_only(db, flag):
    flag()
    rider = await make_rider(db)
    await payments.request_collection(db, "ORD3", rider.id, 80)
    assert await payments.reverse(db, "ORD3", rider.id, 80)
    assert (await payments.get_balance(db, rider.id))["pending"] == 0


async def test_ledger_is_append_only(db, flag):
    flag()
    rider = await make_rider(db)
    await payments.request_collection(db, "ORD4", rider.id, 50)
    with pytest.raises(Exception, match="append-only"):
        await db.execute(text("UPDATE payments.wallet_entries SET amount = 1"))


async def _deliverable(db, rider, mode="included"):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel, status="on_the_way")
    order.rider_id = rider.id
    order.rider_fee_mode = mode
    await db.flush()
    return order


async def test_hook_off_changes_nothing(db, flag):
    flag(enabled=False)
    rider = await make_rider(db)
    order = await _deliverable(db, rider)
    await delivery.delivered(
        db, order.id, rider.id, code=order.delivery_code, cash_fee_received=None, now=utcnow()
    )
    assert (await db.scalar(text("SELECT count(*) FROM payments.wallet_entries"))) == 0


async def test_code_entry_credits_rider_instantly(db, flag):
    flag(shadow=True)
    rider = await make_rider(db)
    order = await _deliverable(db, rider)
    await delivery.delivered(
        db, order.id, rider.id, code=order.delivery_code, cash_fee_received=None, now=utcnow()
    )
    assert order.status == "delivered"
    assert (await payments.get_balance(db, rider.id))["available"] == order.rider_fee


async def test_failed_credit_raises_so_delivery_rolls_back(db, flag, monkeypatch):
    flag(shadow=True)

    async def boom(*a, **k):
        raise RuntimeError("ledger down")

    monkeypatch.setattr("app.payments.service.ledger.move", boom)
    rider = await make_rider(db)
    order = await _deliverable(db, rider)
    with pytest.raises(RuntimeError):
        await delivery.delivered(
            db, order.id, rider.id, code=order.delivery_code, cash_fee_received=None, now=utcnow()
        )
