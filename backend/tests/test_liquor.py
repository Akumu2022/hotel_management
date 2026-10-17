"""Liquor stores: same workings as hotels, listed apart, licence-gated, 18+ confirmed."""

from datetime import date

import pytest

from app.api.v1 import ordering
from tests.factories import make_hotel
from tests.test_admin import HOTEL, headers  # noqa: F401
from tests.test_ordering import NOW, body, key, open_hotel, set_zone


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(ordering, "utcnow", lambda: NOW)


async def liquor(db, **kw):
    kw.setdefault("kind", "liquor")
    kw.setdefault("liquor_licence_no", "BG/123")
    kw.setdefault("liquor_licence_expires", date(2030, 1, 1))
    hotel, product = await open_hotel(db, **kw)
    await set_zone(db)
    return hotel, product


async def test_home_lists_hotels_by_default_and_liquor_on_request(client, db):
    food = await make_hotel(db)
    store, _ = await liquor(db)
    default = {h["slug"] for h in (await client.get("/api/v1/hotels")).json()}
    assert food.slug in default and store.slug not in default
    rows = (await client.get("/api/v1/hotels?kind=liquor")).json()
    assert [h["slug"] for h in rows] == [store.slug]
    assert rows[0]["kind"] == "liquor"
    hit = await client.get("/api/v1/search?q=pilau")
    assert store.slug not in {h["hotel_slug"] for h in hit.json()}
    hit = await client.get("/api/v1/search?q=pilau&kind=liquor")
    assert store.slug in {h["hotel_slug"] for h in hit.json()}


async def test_liquor_order_needs_age_confirmation(client, db):
    store, product = await liquor(db)
    r = await client.post("/api/v1/orders", headers=key(), json=body(store, product))
    assert r.status_code == 422 and r.json()["error"]["code"] == "age_required"
    r = await client.post(
        "/api/v1/orders", headers=key(), json=body(store, product, age_confirmed=True)
    )
    assert r.status_code == 201, r.text


async def test_food_orders_do_not_need_age_confirmation(client, db):
    hotel, product = await open_hotel(db)
    await set_zone(db)
    r = await client.post("/api/v1/orders", headers=key(), json=body(hotel, product))
    assert r.status_code == 201, r.text


async def test_expired_licence_stops_orders_and_shows_closed(client, db):
    store, product = await liquor(db, liquor_licence_expires=date(2026, 9, 30))
    r = await client.post(
        "/api/v1/orders", headers=key(), json=body(store, product, age_confirmed=True)
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "hotel_closed"
    card = (await client.get("/api/v1/hotels?kind=liquor")).json()[0]
    assert card["is_open"] is False


async def test_admin_makes_a_liquor_store_with_nothing_but_the_basics(client, headers):  # noqa: F811
    # No commission, no licence, no hours are needed to onboard a store.
    r = await client.post("/api/v1/admin/hotels", headers=headers, json={**HOTEL, "kind": "liquor"})
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["kind"] == "liquor" and out["commission_percent"] is None
    assert out["liquor_licence_no"] is None and out["has_hours"] is False
    # The store reads closed until it has hours and a licence: that is visible on the owner's list.
    cards = (await client.get("/api/v1/hotels?kind=liquor")).json()
    assert next(h for h in cards if h["slug"] == HOTEL["slug"])["is_open"] is False


async def test_licence_number_and_expiry_go_together(client, headers):  # noqa: F811
    r = await client.post(
        "/api/v1/admin/hotels",
        headers=headers,
        json={**HOTEL, "kind": "liquor", "liquor_licence_no": "BG/777"},
    )
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/admin/hotels",
        headers=headers,
        json={**HOTEL, "kind": "liquor", "liquor_licence_no": "BG/777", "liquor_licence_expires": "2030-06-30"},
    )
    assert r.status_code == 201, r.text
    hid = r.json()["id"]
    r = await client.patch(
        f"/api/v1/admin/hotels/{hid}", headers=headers, json={"liquor_licence_no": None}
    )
    assert r.status_code == 422  # clearing only one half is refused


async def test_owner_can_set_opening_hours_at_creation_and_later(client, headers):  # noqa: F811
    day = {"opens_at": "00:00:00", "closes_at": "23:59:00"}
    r = await client.post(
        "/api/v1/admin/hotels",
        headers=headers,
        json={
            **HOTEL,
            "kind": "liquor",
            "liquor_licence_no": "BG/1",
            "liquor_licence_expires": "2031-01-01",
            **day,
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["has_hours"] is True
    hid = r.json()["id"]
    card = next(h for h in (await client.get("/api/v1/hotels?kind=liquor")).json() if h["slug"] == HOTEL["slug"])
    assert card["is_open"] is True
    r = await client.put(f"/api/v1/admin/hotels/{hid}/hours", headers=headers, json={"hours": []})
    assert r.status_code == 200 and r.json()["has_hours"] is False
    r = await client.put(
        f"/api/v1/admin/hotels/{hid}/hours",
        headers=headers,
        json={"hours": [{"weekday": d, **day} for d in range(7)]},
    )
    assert r.status_code == 200 and r.json()["has_hours"] is True
    dup = {"hours": [{"weekday": 1, **day}, {"weekday": 1, **day}]}
    assert (await client.put(f"/api/v1/admin/hotels/{hid}/hours", headers=headers, json=dup)).status_code == 422
    one = {**HOTEL, "slug": "other-store", "phone": "0712000999", "till_number": "888888", "opens_at": "08:00:00"}
    assert (await client.post("/api/v1/admin/hotels", headers=headers, json=one)).status_code == 422


async def test_liquor_has_its_own_fees_and_delivery(client, db, headers):  # noqa: F811
    food, fproduct = await open_hotel(db)
    store, sproduct = await liquor(db)
    await set_zone(db)

    def quote_body(hotel, product):
        b = body(hotel, product)
        return {k: b[k] for k in ("hotel_slug", "lines", "type", "rider_fee_mode", "phone", "lat", "lng")}

    before = (await client.post("/api/v1/quotes", json=quote_body(store, sproduct))).json()
    # Until set, liquor follows the food values; its bonuses are off.
    liquor_now = (await client.get("/api/v1/admin/settings?kind=liquor", headers=headers)).json()
    assert liquor_now["stamp_reward"] == 0 and liquor_now["free_delivery_min_food"] == 0

    r = await client.put(
        "/api/v1/admin/settings?kind=liquor",
        headers=headers,
        json={
            "service_fee": 45,
            "rider_fee_mode": "bands",
            "rider_fee_bands": [{"max_km": 30, "fee": 300}],
        },
    )
    assert r.status_code == 200, r.text
    after = (await client.post("/api/v1/quotes", json=quote_body(store, sproduct))).json()
    assert after["rider_fee"] == 300 and after["service_fee"] == 45
    assert before["rider_fee"] != 300
    # The food side did not move.
    food_quote = (await client.post("/api/v1/quotes", json=quote_body(food, fproduct))).json()
    assert food_quote["rider_fee"] != 300 and food_quote["service_fee"] != 45
    food_settings = (await client.get("/api/v1/admin/settings", headers=headers)).json()
    assert food_settings["service_fee"] != 45 and food_settings["rider_fee_mode"] != "bands"
    # Non-liquor fields sent with kind=liquor are ignored, not applied to anything.
    await client.put("/api/v1/admin/settings?kind=liquor", headers=headers, json={"banner_title": "X"})
    assert (await client.get("/api/v1/admin/settings", headers=headers)).json()["banner_title"] != "X"


async def test_liquor_is_delivery_or_pickup_only(client, db):
    store, product = await liquor(db)
    r = await client.post(
        "/api/v1/quotes", json={**{k: body(store, product)[k] for k in ("hotel_slug", "lines", "rider_fee_mode", "phone")}, "type": "eat_in", "rider_fee_mode": "none"}
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "eat_in_unavailable"


async def test_track_and_store_settings_say_what_kind_of_store_it_is(client, db):
    from tests.factories import auth_header, make_user

    store, product = await liquor(db)
    placed = await client.post(
        "/api/v1/orders", headers=key(), json=body(store, product, age_confirmed=True)
    )
    token = placed.json()["tracking_token"]
    assert (await client.get(f"/api/v1/track/{token}")).json()["hotel_kind"] == "liquor"
    staff = auth_header(await make_user(db, "hotel_admin", store))
    assert (await client.get("/api/v1/hotel/settings", headers=staff)).json()["kind"] == "liquor"


async def test_owner_can_renew_a_licence_date(client, db, headers):  # noqa: F811
    store, _ = await liquor(db)
    r = await client.patch(
        f"/api/v1/admin/hotels/{store.id}",
        headers=headers,
        json={"liquor_licence_expires": "2032-06-30"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["liquor_licence_expires"] == "2032-06-30"
