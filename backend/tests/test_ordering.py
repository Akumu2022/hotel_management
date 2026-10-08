"""M3 acceptance: idempotent placement and totals matching the section 11 worked example."""

import asyncio
import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import func, select

from app.api.v1 import ordering
from app.models import (
    Customer,
    Discount,
    HotelHours,
    LedgerEntry,
    Order,
    OrderItem,
    Refund,
)
from app.schemas.orders import OrderIn
from app.services import ledger, orders, settings
from tests.factories import make_hotel, make_product

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)  # 12:00 in Nairobi
ZONE = [[36.80, -1.30], [36.85, -1.30], [36.85, -1.25], [36.80, -1.25]]
INSIDE = {"lat": -1.28, "lng": 36.82}


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(ordering, "utcnow", lambda: NOW)


async def open_hotel(session, **kw):
    hotel = await make_hotel(session, **kw)
    session.add_all(
        HotelHours(hotel_id=hotel.id, weekday=d, opens_at=time(7), closes_at=time(22))
        for d in range(7)
    )
    product = await make_product(session, hotel, price=650, name="Pilau")
    await session.flush()
    return hotel, product


async def set_zone(session):
    await settings.update(session, {"delivery_zone": ZONE}, None)


def body(hotel, product, **kw) -> dict:
    data = {
        "hotel_slug": hotel.slug,
        "lines": [{"product_id": str(product.id), "quantity": 1}],
        "type": "delivery",
        "rider_fee_mode": "included",
        "name": "Achieng",
        "phone": "0712000111",
        "payment_method": "mpesa",
        "landmark": "Blue gate opposite the chemist",
        "expected_total": 670,
        **INSIDE,
    }
    data.update(kw)
    return data


def key() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


@pytest.fixture
async def shop(db):
    hotel, product = await open_hotel(db)
    await set_zone(db)
    return hotel, product


# --- Quotes: section 11 worked example ----------------------------------------------------------


@pytest.mark.parametrize(
    ("order_type", "mode", "till", "cash"),
    [("delivery", "included", 670, 100), ("delivery", "cash", 670, 100), ("pickup", "none", 670, 0)],
)
async def test_quote_worked_example(client, shop, order_type, mode, till, cash):
    hotel, product = shop
    r = await client.post(
        "/api/v1/quotes",
        json={
            "hotel_slug": hotel.slug,
            "lines": [{"product_id": str(product.id), "quantity": 1}],
            "type": order_type,
            "rider_fee_mode": mode,
        },
    )
    assert r.status_code == 200, r.text
    q = r.json()
    assert (q["food_net"], q["service_fee"], q["till_amount"], q["rider_fee_cash"]) == (
        650,
        20,
        till,
        cash,
    )


async def test_quote_ignores_client_prices(client, shop):
    hotel, product = shop
    r = await client.post(
        "/api/v1/quotes",
        json={
            "hotel_slug": hotel.slug,
            "lines": [{"product_id": str(product.id), "quantity": 1, "price": 1}],
            "type": "pickup",
            "rider_fee_mode": "none",
        },
    )
    assert r.status_code == 422  # unknown fields are rejected outright


# --- Placement --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kw", "till"),
    [
        ({}, 670),
        ({"rider_fee_mode": "cash", "expected_total": 670}, 670),
        ({"type": "pickup", "rider_fee_mode": "none", "expected_total": 670}, 670),
    ],
)
async def test_place_order_snapshots_money(client, db, shop, kw, till):
    hotel, product = shop
    r = await client.post("/api/v1/orders", headers=key(), json=body(hotel, product, **kw))
    assert r.status_code == 201, r.text
    placed = r.json()
    assert placed["till_amount"] == till
    assert placed["till_number"] == hotel.till_number
    assert placed["expires_at"] is not None

    order = (await db.execute(select(Order).where(Order.code == placed["code"]))).scalar_one()
    # Flat tier (D19): food 650 is in the 501-1,000 band.
    assert (order.commission_amount, order.service_fee, order.commission_bp) == (30, 20, 0)
    assert order.food_net + order.service_fee + order.rider_fee_in_till == till
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
    assert (item.name_snapshot, item.unit_price, item.line_total) == ("Pilau", 650, 650)
    assert (await db.get(Customer, "254712000111")).name == "Achieng"


async def test_same_key_same_request_returns_same_order(client, shop):
    hotel, product = shop
    h, data = key(), body(hotel, product)
    first = await client.post("/api/v1/orders", headers=h, json=data)
    second = await client.post("/api/v1/orders", headers=h, json=data)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["code"] == second.json()["code"]


async def test_same_key_different_request_is_409(client, shop):
    hotel, product = shop
    h = key()
    await client.post("/api/v1/orders", headers=h, json=body(hotel, product))
    r = await client.post(
        "/api/v1/orders", headers=h, json=body(hotel, product, landmark="Another place entirely")
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "idempotency_conflict"


async def test_missing_idempotency_key(client, shop):
    hotel, product = shop
    r = await client.post("/api/v1/orders", json=body(hotel, product))
    assert r.status_code == 400


async def test_price_changed_returns_new_quote(client, db, shop):
    hotel, product = shop
    product.price = 700
    await db.flush()
    h = key()
    r = await client.post("/api/v1/orders", headers=h, json=body(hotel, product))
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "price_changed"
    assert err["quote"]["till_amount"] == 720
    # The customer confirms the new total; the same key with the new body now works because the
    # failed attempt left nothing behind.
    r = await client.post(
        "/api/v1/orders", headers=h, json=body(hotel, product, expected_total=720)
    )
    assert r.status_code == 201


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ({"status": "paused"}, "hotel_closed"),
        ({"accepting_orders": False}, "hotel_closed"),
    ],
)
async def test_hotel_state_rules(client, db, shop, change, code):
    hotel, product = shop
    for k, v in change.items():
        setattr(hotel, k, v)
    await db.flush()
    r = await client.post("/api/v1/orders", headers=key(), json=body(hotel, product))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == code


async def test_closed_outside_hours_and_cutoff(client, db, shop, monkeypatch):
    hotel, product = shop
    for t, ok in [
        (datetime(2026, 10, 2, 18, 50, tzinfo=UTC), False),  # 21:50, past cut-off
        (datetime(2026, 10, 2, 3, 0, tzinfo=UTC), False),  # 06:00, not open yet
        (datetime(2026, 10, 2, 18, 40, tzinfo=UTC), True),
    ]:  # 21:40
        monkeypatch.setattr(ordering, "utcnow", lambda t=t: t)
        r = await client.post("/api/v1/orders", headers=key(), json=body(hotel, product))
        assert (r.status_code == 201) == ok, (t, r.text)


async def test_sold_out_and_time_window(client, db, shop):
    hotel, product = shop
    product.is_sold_out = True
    await db.flush()
    r = await client.post("/api/v1/orders", headers=key(), json=body(hotel, product))
    assert r.json()["error"]["code"] == "item_sold_out"

    product.is_sold_out = False
    from app.models import Category

    cat = await db.get(Category, product.category_id)
    cat.available_from, cat.available_to = time(6), time(10)  # breakfast; NOW is 12:00
    await db.flush()
    r = await client.post("/api/v1/orders", headers=key(), json=body(hotel, product))
    assert r.json()["error"]["code"] == "item_unavailable"


async def test_product_from_another_hotel_is_unavailable(client, db, shop):
    hotel, _ = shop
    _, other_product = await open_hotel(db)
    r = await client.post("/api/v1/orders", headers=key(), json=body(hotel, other_product))
    assert r.json()["error"]["code"] == "item_unavailable"


async def test_delivery_zone_rules(client, db, shop):
    hotel, product = shop
    r = await client.post(
        "/api/v1/orders", headers=key(), json=body(hotel, product, lat=-1.0, lng=37.0)
    )
    assert r.json()["error"]["code"] == "outside_zone"


@pytest.mark.parametrize(
    "kw",
    [
        {"payment_method": "cash"},  # cash is pickup only
        {"landmark": ""},
        {"lat": None},
        {"type": "pickup"},  # pickup with a rider fee mode
        {"lines": []},
        {"name": "A"},
        {"phone": "12345"},
    ],
)
async def test_validation(client, shop, kw):
    hotel, product = shop
    r = await client.post("/api/v1/orders", headers=key(), json=body(hotel, product, **kw))
    assert r.status_code == 422, r.text


# --- Everything is paid first (D34) -------------------------------------------------------------


@pytest.mark.parametrize("loyal", [False, True])
@pytest.mark.parametrize("hotel_allows_cash", [True, False])
async def test_cash_on_pickup_is_refused_for_everyone(client, db, shop, loyal, hotel_allows_cash):
    """Nobody can order and not turn up: no order is made without M-Pesa, whatever the hotel's old
    setting says or however many orders the customer has finished."""
    hotel, product = shop
    hotel.cash_pickup_enabled = hotel_allows_cash
    if loyal:
        db.add(Customer(phone="254712000111", name="Achieng", completed_orders=3))
    await db.flush()
    pickup = {"type": "pickup", "rider_fee_mode": "none", "payment_method": "cash"}
    r = await client.post(
        "/api/v1/orders", headers=key(), json=body(hotel, product, expected_total=670, **pickup)
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "cash_not_accepted"
    assert r.json()["error"]["field"] == "payment_method"
    count = await db.scalar(select(func.count()).select_from(Order))
    assert count == 0  # nothing was created


async def test_pickup_by_mpesa_still_works_and_waits_for_payment(client, db, shop):
    hotel, product = shop
    pickup = {"type": "pickup", "rider_fee_mode": "none", "payment_method": "mpesa"}
    r = await client.post(
        "/api/v1/orders", headers=key(), json=body(hotel, product, expected_total=670, **pickup)
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "awaiting_payment" and r.json()["expires_at"] is not None


async def test_the_quote_and_the_public_hotel_say_cash_is_off(client, db, shop):
    hotel, product = shop
    q = await client.post(
        "/api/v1/quotes", json={k: v for k, v in body(hotel, product).items() if k in ("hotel_slug", "lines", "type", "rider_fee_mode", "lat", "lng")}
    )
    assert q.status_code == 200 and q.json()["cash_allowed"] is False
    hotels = (await client.get("/api/v1/hotels")).json()
    assert all(h["cash_pickup_enabled"] is False for h in hotels)


async def test_blocklist_and_option_b(client, db, shop):
    hotel, product = shop
    db.add(Customer(phone="254712000111", name="X", option_b_blocked=True))
    await db.flush()
    r = await client.post(
        "/api/v1/orders",
        headers=key(),
        json=body(hotel, product, rider_fee_mode="cash", expected_total=670),
    )
    assert r.json()["error"]["code"] == "option_b_unavailable"
    q = await client.post(
        "/api/v1/quotes",
        json={
            "hotel_slug": hotel.slug,
            "lines": [{"product_id": str(product.id), "quantity": 1}],
            "type": "delivery",
            "rider_fee_mode": "included",
            "phone": "0712000111",
        },
    )
    assert q.json()["option_b_allowed"] is False

    (await db.get(Customer, "254712000111")).blocklisted = True
    await db.flush()
    r = await client.post("/api/v1/orders", headers=key(), json=body(hotel, product))
    assert r.status_code == 403


async def test_promo_one_use_per_phone(client, db, shop):
    hotel, product = shop
    db.add(
        Discount(
            hotel_id=hotel.id,
            scope="order",
            kind="fixed",
            value=50,
            promo_code="KARIBU",
            starts_at=NOW - timedelta(days=1),
        )
    )
    await db.flush()
    data = body(hotel, product, promo_code="karibu", expected_total=620)
    r = await client.post("/api/v1/orders", headers=key(), json=data)
    assert r.status_code == 201, r.text
    r = await client.post("/api/v1/orders", headers=key(), json=data)
    assert r.json()["error"]["code"] == "promo_already_used"
    other = body(hotel, product, promo_code="KARIBU", expected_total=620, phone="0712000222")
    assert (await client.post("/api/v1/orders", headers=key(), json=other)).status_code == 201


# --- Tracking and cancel ----------------------------------------------------------------------


async def test_tracking_and_cancel(client, db, shop):
    hotel, product = shop
    placed = (await client.post("/api/v1/orders", headers=key(), json=body(hotel, product))).json()
    token = placed["tracking_token"]
    t = (await client.get(f"/api/v1/track/{token}")).json()
    assert t["status"] == "awaiting_payment"
    assert len(t["delivery_code"]) == 4
    assert t["items"][0]["name"] == "Pilau"
    assert t["can_cancel"] is True
    assert [e["status"] for e in t["events"]] == ["awaiting_payment"]

    assert (await client.post(f"/api/v1/track/{token}/cancel")).json()["status"] == "cancelled"
    assert (await client.post(f"/api/v1/track/{token}/cancel")).status_code == 200  # repeat tap
    t = (await client.get(f"/api/v1/track/{token}")).json()
    assert t["status"] == "cancelled" and t["can_cancel"] is False
    assert (await client.get("/api/v1/track/not-a-real-token")).status_code == 404


async def test_cancel_after_acceptance_refused(client, db, shop):
    hotel, product = shop
    placed = (await client.post("/api/v1/orders", headers=key(), json=body(hotel, product))).json()
    order = (await db.execute(select(Order).where(Order.code == placed["code"]))).scalar_one()
    order.status = "accepted"
    await db.flush()
    r = await client.post(f"/api/v1/track/{placed['tracking_token']}/cancel")
    assert r.status_code == 409


async def test_cancel_paid_order_creates_full_refund(client, db, shop):
    hotel, product = shop
    placed = (await client.post("/api/v1/orders", headers=key(), json=body(hotel, product))).json()
    order = (await db.execute(select(Order).where(Order.code == placed["code"]))).scalar_one()
    await ledger.record_payment(db, order, amount=770, reference="TJ1")
    order.status = "paid"
    await db.flush()
    await client.post(f"/api/v1/track/{placed['tracking_token']}/cancel")
    refund = (await db.execute(select(Refund).where(Refund.order_id == order.id))).scalar_one()
    assert refund.amount == 770
    reversal = await db.scalar(
        select(func.sum(LedgerEntry.amount)).where(
            LedgerEntry.order_id == order.id, LedgerEntry.entry_type == "commission_reversal"
        )
    )
    assert reversal == 30  # the whole tier fee


# --- Concurrency: 50 simultaneous duplicate submissions -> one order ---------------------------


async def test_50_simultaneous_duplicates_create_one_order(committed):
    async with committed() as s:
        hotel, product = await open_hotel(s)
        await set_zone(s)
        await s.commit()
    data = OrderIn.model_validate(body(hotel, product))
    idem = uuid.uuid4().hex

    async def submit():
        async with committed() as s:
            order, _ = await orders.place(s, data, idem, NOW)
            await s.commit()
            return order.code

    codes = await asyncio.gather(*(submit() for _ in range(50)))
    assert len(set(codes)) == 1

    async with committed() as s:
        count = await s.scalar(select(func.count()).select_from(Order))
        assert count == 1


async def test_public_config(client, db):
    cfg = (await client.get("/api/v1/config")).json()
    assert cfg["delivery_mode"] == "distance" and cfg["max_delivery_km"] == 10
    await set_zone(db)
    cfg = (await client.get("/api/v1/config")).json()
    assert cfg["delivery_mode"] == "area" and cfg["delivery_zone"] == ZONE


# --- Distance-based rider fee (DECISIONS D14) ---------------------------------------------------

HOTEL_AT = {"lat": -1.2864, "lng": 36.8172}


def quote_body(hotel, product, **kw):
    return {
        "hotel_slug": hotel.slug,
        "lines": [{"product_id": str(product.id), "quantity": 1}],
        "type": "delivery",
        "rider_fee_mode": "included",
        **kw,
    }


async def test_rider_fee_from_distance(client, db, shop):
    hotel, product = shop
    hotel.lat, hotel.lng = HOTEL_AT["lat"], HOTEL_AT["lng"]
    await settings.update(db, {"rider_fee_mode": "bands", "distance_method": "straight"}, None)
    await db.flush()
    # No pin yet: the nearest band, flagged as an estimate.
    q = (await client.post("/api/v1/quotes", json=quote_body(hotel, product))).json()
    assert (q["rider_fee"], q["rider_fee_estimated"], q["distance_km"]) == (100, True, None)
    # ~3 km away: second band.
    q = (
        await client.post(
            "/api/v1/quotes", json=quote_body(hotel, product, lat=-1.2648, lng=36.8025)
        )
    ).json()
    assert q["rider_fee"] == 150 and q["rider_fee_estimated"] is False
    assert 2.5 < q["distance_km"] < 3.5
    assert q["till_amount"] == 650 + 20  # D35: the rider fee never goes through the hotel Till
    # Placing the order charges the same distance fee.
    r = await client.post(
        "/api/v1/orders",
        headers=key(),
        json=body(hotel, product, lat=-1.2648, lng=36.8025, expected_total=670),
    )
    assert r.status_code == 201, r.text
    order = (await db.execute(select(Order).where(Order.code == r.json()["code"]))).scalar_one()
    assert (order.rider_fee, order.rider_fee_in_till) == (150, 0)


async def test_too_far_is_refused(client, db, shop):
    hotel, product = shop
    hotel.lat, hotel.lng = -1.20, 36.70  # ~16 km from INSIDE
    await db.flush()
    q = (await client.post("/api/v1/quotes", json=quote_body(hotel, product, **INSIDE))).json()
    assert q["too_far"] is True
    r = await client.post(
        "/api/v1/orders", headers=key(), json=body(hotel, product, expected_total=q["till_amount"])
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "too_far"


async def test_pickup_has_no_rider_fee_regardless_of_location(client, db, shop):
    hotel, product = shop
    hotel.lat, hotel.lng = HOTEL_AT["lat"], HOTEL_AT["lng"]
    await db.flush()
    q = (
        await client.post(
            "/api/v1/quotes",
            json=quote_body(hotel, product, type="pickup", rider_fee_mode="none", **INSIDE),
        )
    ).json()
    assert (q["rider_fee"], q["till_amount"]) == (0, 670)


async def test_per_km_pricing_and_order_snapshot(client, db, shop):
    hotel, product = shop
    hotel.lat, hotel.lng = HOTEL_AT["lat"], HOTEL_AT["lng"]
    await settings.update(
        db,
        {
            "rider_fee_mode": "per_km",
            "rider_fee_base": 50,
            "rider_fee_per_km": 20,
            "rider_fee_min": 100,
            "rider_fee_max_km": 10,
            "distance_method": "straight",
        },
        None,
    )
    await db.flush()
    pin = {"lat": -1.2648, "lng": 36.8025}  # ~2.9 km: 50 + 20 x 2.9 = 108 -> 110
    q = (await client.post("/api/v1/quotes", json=quote_body(hotel, product, **pin))).json()
    assert q["rider_fee"] == 110 and q["max_delivery_km"] == 10
    r = await client.post(
        "/api/v1/orders", headers=key(), json=body(hotel, product, expected_total=670, **pin)
    )
    assert r.status_code == 201, r.text
    # The same distance and fee are stored on the order and shown when tracking.
    t = (await client.get(f"/api/v1/track/{r.json()['tracking_token']}")).json()
    assert t["distance_km"] == q["distance_km"] and t["rider_fee"] == 110


async def test_road_distance_falls_back_to_estimate(client, db, shop):
    hotel, product = shop
    hotel.lat, hotel.lng = HOTEL_AT["lat"], HOTEL_AT["lng"]
    await settings.update(db, {"distance_method": "road"}, None)
    await db.flush()
    pin = {"lat": -1.2648, "lng": 36.8025}
    q = (await client.post("/api/v1/quotes", json=quote_body(hotel, product, **pin))).json()
    straight = settings.distance_km(HOTEL_AT["lat"], HOTEL_AT["lng"], pin["lat"], pin["lng"])
    assert q["distance_km"] == round(straight * 1.3, 1)  # routing offline in tests


async def test_without_area_hotels_deliver_by_distance(client, db, shop):
    hotel, product = shop
    await settings.update(db, {"delivery_zone": []}, None)
    await db.flush()
    # No area and no hotel location: delivery refused with a clear reason.
    r = await client.post("/api/v1/orders", headers=key(), json=body(hotel, product))
    assert r.json()["error"]["code"] == "delivery_unavailable"
    # Give the hotel a location: anywhere within the max distance works, no area needed.
    hotel.lat, hotel.lng = -1.28, 36.82
    await db.flush()
    q = (await client.post("/api/v1/quotes", json=quote_body(hotel, product, **INSIDE))).json()
    r = await client.post(
        "/api/v1/orders", headers=key(), json=body(hotel, product, expected_total=q["till_amount"])
    )
    assert r.status_code == 201, r.text


async def test_order_history_by_tokens(client, db, shop):
    hotel, product = shop
    r = await client.post("/api/v1/orders", headers=key(), json=body(hotel, product))
    token = r.json()["tracking_token"]
    rows = (await client.post("/api/v1/track/history", json={"tokens": [token, "x" * 20]})).json()
    assert len(rows) == 1  # unknown tokens are ignored, nothing else is revealed
    h = rows[0]
    assert (h["code"], h["till_amount"], h["paid"], h["refunded"]) == (r.json()["code"], 670, 0, 0)
    assert h["items"] == ["1× Pilau"] and h["hotel_slug"] == hotel.slug
    r = await client.post("/api/v1/track/history", json={"tokens": ["y" * 20] * 201})
    assert r.status_code == 422


async def test_hotel_admin_edits_identity_with_audit(client, db):
    from app.models import AuditLog
    from tests.factories import auth_header, make_order, make_user

    hotel = await open_hotel(db)
    hotel = hotel[0]
    other = await make_hotel(db)
    admin = auth_header(await make_user(db, "hotel_admin", hotel))
    r = await client.put(
        "/api/v1/hotel/settings",
        headers=admin,
        json={"name": "Noor Cafe", "phone": "0711222333", "till_number": "5559876"},
    )
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["phone"], r.json()["till_number"]) == (
        "Noor Cafe",
        "254711222333",
        "5559876",
    )
    log = (
        (await db.execute(select(AuditLog).where(AuditLog.target_id == str(hotel.id))))
        .scalars()
        .all()
    )
    assert {*log[-1].details} == {"name", "phone", "till_number"}

    r = await client.put(
        "/api/v1/hotel/settings", headers=admin, json={"till_number": other.till_number}
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "duplicate"
    await make_order(db, hotel)  # a customer is paying to the current Till
    r = await client.put("/api/v1/hotel/settings", headers=admin, json={"till_number": "5550000"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "orders_paying"
    cashier = auth_header(await make_user(db, "cashier", hotel))
    r = await client.put("/api/v1/hotel/settings", headers=cashier, json={"name": "Hacked"})
    assert r.status_code == 403


async def test_the_hotel_never_handles_the_rider_fee(client, db, shop):
    """D35: even an old app asking for 'fee with the order' gets 'customer pays the rider'."""
    hotel, product = shop
    r = await client.post(
        "/api/v1/orders", headers=key(), json=body(hotel, product, rider_fee_mode="included")
    )
    assert r.status_code == 201, r.text
    order = (await db.execute(select(Order).where(Order.code == r.json()["code"]))).scalar_one()
    assert order.rider_fee_mode == "cash"
    assert order.rider_fee_in_till == 0 and order.rider_fee > 0
    assert order.till_amount == order.till_amount - order.rider_fee_in_till
