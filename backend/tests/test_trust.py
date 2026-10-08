"""Customer trust: the Till's registered name, and "checked by the Chakula team"."""

import pytest

from app.api.v1 import ordering
from app.core.time import utcnow
from tests.factories import auth_header, make_hotel, make_user
from tests.test_ordering import NOW, body, key, open_hotel, set_zone

API = "/api/v1"

NEW_HOTEL = {
    "name": "Noor Cafe",
    "slug": "noor-cafe-test",
    "phone": "0712333444",
    "till_number": "5550999",
}


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(ordering, "utcnow", lambda: NOW)


async def public_hotel(client, slug):
    return next(h for h in (await client.get(f"{API}/hotels")).json() if h["slug"] == slug)


async def test_a_new_hotel_is_unverified_until_the_admin_checks_it(client, db):
    admin = auth_header(await make_user(db, "super_admin"))
    r = await client.post(f"{API}/admin/hotels", headers=admin, json={**NEW_HOTEL, "till_name": "NOOR CAFE LTD"})
    assert r.status_code == 201, r.text
    assert (r.json()["verified"], r.json()["till_name"]) == (False, "NOOR CAFE LTD")
    shown = await public_hotel(client, NEW_HOTEL["slug"])
    assert (shown["verified"], shown["till_name"]) == (False, "NOOR CAFE LTD")

    r = await client.patch(f"{API}/admin/hotels/{r.json()['id']}", headers=admin, json={"verified": True})
    assert r.status_code == 200 and r.json()["verified"] is True
    assert (await public_hotel(client, NEW_HOTEL["slug"]))["verified"] is True


async def test_the_admin_can_create_a_hotel_already_verified(client, db):
    admin = auth_header(await make_user(db, "super_admin"))
    r = await client.post(f"{API}/admin/hotels", headers=admin, json={**NEW_HOTEL, "verified": True, "till_name": "NOOR CAFE LTD"})
    assert r.status_code == 201 and r.json()["verified"] is True


async def test_verification_is_audited_and_can_be_withdrawn(client, db):
    admin = auth_header(await make_user(db, "super_admin"))
    hotel = await make_hotel(db)
    await client.patch(f"{API}/admin/hotels/{hotel.id}", headers=admin, json={"verified": True})
    r = await client.patch(f"{API}/admin/hotels/{hotel.id}", headers=admin, json={"verified": False})
    assert r.json()["verified"] is False
    assert (await public_hotel(client, hotel.slug))["verified"] is False


async def test_a_hotel_cannot_verify_itself(client, db):
    hotel = await make_hotel(db)
    staff = auth_header(await make_user(db, "hotel_admin", hotel))
    r = await client.put(f"{API}/hotel/settings", headers=staff, json={"verified": True})
    assert r.status_code == 422  # not a field the hotel can send
    r = await client.put(f"{API}/hotel/settings", headers=staff, json={"till_name": "MY OWN NAME"})
    assert r.status_code == 422
    await db.refresh(hotel)
    assert hotel.verified_at is None and hotel.till_name is None


async def test_the_hotel_sees_its_own_check_status(client, db):
    hotel = await make_hotel(db)
    hotel.verified_at, hotel.till_name = utcnow(), "NOOR CAFE LTD"
    staff = auth_header(await make_user(db, "hotel_admin", hotel))
    await db.flush()
    s = (await client.get(f"{API}/hotel/settings", headers=staff)).json()
    assert (s["verified"], s["till_name"]) == (True, "NOOR CAFE LTD")


async def test_a_hotel_changing_its_till_loses_the_check_and_the_name(client, db):
    hotel = await make_hotel(db)
    hotel.verified_at, hotel.till_name = utcnow(), "NOOR CAFE LTD"
    staff = auth_header(await make_user(db, "hotel_admin", hotel))
    await db.flush()
    r = await client.put(f"{API}/hotel/settings", headers=staff, json={"till_number": "5559876"})
    assert r.status_code == 200, r.text
    shown = await public_hotel(client, hotel.slug)
    assert (shown["verified"], shown["till_name"]) == (False, None)  # needs checking again


async def test_changing_other_details_keeps_the_check(client, db):
    hotel = await make_hotel(db)
    hotel.verified_at = utcnow()
    staff = auth_header(await make_user(db, "hotel_admin", hotel))
    await db.flush()
    r = await client.put(f"{API}/hotel/settings", headers=staff, json={"accepting_orders": False})
    assert r.status_code == 200
    assert (await public_hotel(client, hotel.slug))["verified"] is True


async def test_the_admin_changing_the_till_clears_the_check_unless_they_tick_it_again(client, db):
    admin = auth_header(await make_user(db, "super_admin"))
    hotel = await make_hotel(db)
    hotel.verified_at, hotel.till_name = utcnow(), "OLD NAME"
    await db.flush()
    r = await client.patch(f"{API}/admin/hotels/{hotel.id}", headers=admin, json={"till_number": "5557777"})
    assert r.json()["verified"] is False  # a different Till is a different thing to check
    r = await client.patch(
        f"{API}/admin/hotels/{hotel.id}", headers=admin, json={"till_number": "5558888", "till_name": "NEW NAME", "verified": True}
    )
    assert (r.json()["verified"], r.json()["till_name"]) == (True, "NEW NAME")  # checked in the same step


async def test_the_customer_sees_the_till_name_and_the_check_on_their_order(client, db):
    hotel, product = await open_hotel(db)
    await set_zone(db)
    hotel.till_name, hotel.verified_at = "NOOR CAFE LTD", utcnow()
    await db.flush()
    r = await client.post(f"{API}/orders", json=body(hotel, product), headers=key())
    assert r.status_code == 201, r.text
    t = (await client.get(f"{API}/track/{r.json()['tracking_token']}")).json()
    assert (t["till_name"], t["hotel_verified"]) == ("NOOR CAFE LTD", True)
    assert t["till_number"] == hotel.till_number


async def test_an_unchecked_hotel_shows_no_badge_on_the_order(client, db):
    hotel, product = await open_hotel(db)
    await set_zone(db)
    r = await client.post(f"{API}/orders", json=body(hotel, product), headers=key())
    t = (await client.get(f"{API}/track/{r.json()['tracking_token']}")).json()
    assert (t["till_name"], t["hotel_verified"]) == (None, False)
