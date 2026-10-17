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


async def test_admin_makes_a_liquor_store_with_its_licence(client, headers):  # noqa: F811
    r = await client.post(
        "/api/v1/admin/hotels", headers=headers, json={**HOTEL, "kind": "liquor"}
    )
    assert r.status_code == 422
    r = await client.post(
        "/api/v1/admin/hotels",
        headers=headers,
        json={
            **HOTEL,
            "kind": "liquor",
            "liquor_licence_no": "BG/777",
            "liquor_licence_expires": "2030-06-30",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["kind"] == "liquor" and r.json()["liquor_licence_no"] == "BG/777"
    hid = r.json()["id"]
    r = await client.patch(
        f"/api/v1/admin/hotels/{hid}", headers=headers, json={"liquor_licence_no": None}
    )
    assert r.status_code == 422
