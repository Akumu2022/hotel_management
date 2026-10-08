"""Pickup / eat-in handover PIN: the person at the counter must give the customer's 4-digit PIN."""

import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.api.v1 import ordering
from app.models import Order
from tests.factories import auth_header, make_hotel, make_order, make_user
from tests.test_ordering import NOW, body, key, open_hotel, set_zone

API = "/api/v1"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(ordering, "utcnow", lambda: NOW)


def pickup_body(hotel, product, **kw):
    data = body(hotel, product, type="pickup", rider_fee_mode="none", expected_total=670, **kw)
    for k in ("lat", "lng", "landmark"):
        data.pop(k)
    return data


def eat_in_body(hotel, product, **kw):
    data = body(
        hotel,
        product,
        type="eat_in",
        rider_fee_mode="none",
        arrive_at=(NOW + timedelta(minutes=45)).isoformat(),
        expected_total=650 + 20 + 30,
        **kw,
    )
    for k in ("lat", "lng", "landmark"):
        data.pop(k)
    return data


async def ready_order(db, *, order_type="pickup", pin="4821", **kw):
    hotel = await make_hotel(db)
    staff = await make_user(db, "hotel_admin", hotel)
    delivery = order_type == "delivery"
    order = await make_order(
        db,
        hotel,
        order_type="delivery" if delivery else "pickup",
        rider_fee_mode="included" if delivery else "none",
        status="ready",
        **kw,
    )
    order.delivery_code = pin
    if order_type == "eat_in":  # priced as a pickup, then marked eat in (same trick as test_d28)
        order.type, order.arrive_at = "eat_in", NOW + timedelta(minutes=30)
    await db.flush()
    return hotel, staff, order


async def collect(client, staff, order, code=None):
    payload = {"json": {"code": code}} if code is not None else {}
    return await client.post(
        f"{API}/hotel/orders/{order.id}/collected", headers=auth_header(staff), **payload
    )


# --- Every order gets a PIN ---------------------------------------------------------------------


async def test_every_new_order_type_gets_a_pin_the_customer_can_see(client, db):
    hotel, product = await open_hotel(db)
    await set_zone(db)
    pins = []
    for data in (body(hotel, product), pickup_body(hotel, product), eat_in_body(hotel, product)):
        r = await client.post(f"{API}/orders", json=data, headers=key())
        assert r.status_code == 201, r.text
        t = (await client.get(f"{API}/track/{r.json()['tracking_token']}")).json()
        assert re.fullmatch(r"\d{4}", t["delivery_code"]), t["type"]
        pins.append(t["delivery_code"])
    assert len(pins) == 3


async def test_hotel_never_sees_the_pin(client, db):
    hotel, staff, order = await ready_order(db, pin="7351")
    r = await client.get(f"{API}/hotel/orders", headers=auth_header(staff))
    assert r.status_code == 200
    assert "7351" not in r.text and "delivery_code" not in r.text


# --- Handover -----------------------------------------------------------------------------------


@pytest.mark.parametrize("order_type", ["pickup", "eat_in"])
async def test_correct_pin_hands_over_the_order(client, db, order_type):
    _, staff, order = await ready_order(db, order_type=order_type)
    r = await collect(client, staff, order, "4821")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "collected"


async def test_handover_without_a_pin_is_refused_and_the_order_stays_ready(client, db):
    _, staff, order = await ready_order(db)
    r = await collect(client, staff, order)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "code_required"
    await db.refresh(order)
    assert order.status == "ready"


async def test_wrong_pin_counts_tries_and_keeps_the_order_ready(client, db):
    _, staff, order = await ready_order(db)
    r = await collect(client, staff, order, "0000")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "wrong_code"
    assert "4 tries left" in r.json()["error"]["message"]
    await db.refresh(order)
    assert (order.status, order.delivery_code_attempts) == ("ready", 1)
    assert (await collect(client, staff, order, "4821")).status_code == 200  # still works


async def test_five_wrong_pins_lock_the_handover_even_for_the_right_pin(client, db):
    _, staff, order = await ready_order(db)
    for _ in range(5):
        r = await collect(client, staff, order, "1111")
        assert r.json()["error"]["code"] == "wrong_code"
    assert "Locked" in r.json()["error"]["message"]
    r = await collect(client, staff, order, "4821")
    assert r.status_code == 423
    assert r.json()["error"]["code"] == "code_locked"
    await db.refresh(order)
    assert order.status == "ready"


@pytest.mark.parametrize("bad", ["12", "12345", "abcd", " 482"])
async def test_a_malformed_pin_is_a_validation_error(client, db, bad):
    _, staff, order = await ready_order(db)
    r = await collect(client, staff, order, bad)
    assert r.status_code == 422
    await db.refresh(order)
    assert (order.status, order.delivery_code_attempts) == ("ready", 0)


async def test_repeating_a_finished_handover_is_harmless(client, db):
    _, staff, order = await ready_order(db)
    assert (await collect(client, staff, order, "4821")).status_code == 200
    r = await collect(client, staff, order)  # double tap on bad network: no PIN needed again
    assert r.status_code == 200 and r.json()["status"] == "collected"


async def test_cash_pickup_still_needs_the_pin_and_records_the_cash(client, db):
    _, staff, order = await ready_order(db, payment_method="cash")
    assert (await collect(client, staff, order)).status_code == 422
    r = await collect(client, staff, order, "4821")
    assert r.status_code == 200
    await db.refresh(order)
    assert order.paid_at is not None


async def test_another_hotels_staff_cannot_use_the_pin(client, db):
    _, _, order = await ready_order(db)
    other = await make_user(db, "hotel_admin", await make_hotel(db))
    r = await collect(client, other, order, "4821")
    assert r.status_code == 404


async def test_orders_from_before_pins_existed_are_handed_over_as_before(client, db):
    _, staff, order = await ready_order(db, pin=None)
    r = await collect(client, staff, order)
    assert r.status_code == 200 and r.json()["status"] == "collected"


async def test_a_delivery_order_is_still_never_collected_at_the_counter(client, db):
    _, staff, order = await ready_order(db, order_type="delivery")
    r = await collect(client, staff, order, "4821")
    assert r.status_code == 409
    row = (await db.execute(select(Order).where(Order.id == order.id))).scalar_one()
    assert row.status == "ready"
