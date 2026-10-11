"""The owner's one-hotel view: activity, commission standing and warning signs."""

from datetime import timedelta

from app.core.time import utcnow
from tests.factories import auth_header, make_hotel, make_order, make_user


async def admin_headers(db):
    return auth_header(await make_user(db, "super_admin"))


def paid(order, status, hours_ago=1):
    order.status = status
    order.paid_at = utcnow() - timedelta(hours=hours_ago)
    return order


async def test_overview_of_a_quiet_hotel_has_no_warnings_except_location(client, db):
    headers = await admin_headers(db)
    hotel = await make_hotel(db, lat=0.5636, lng=34.5606)
    paid(await make_order(db, hotel, status="delivered"), "delivered")
    await db.flush()
    r = await client.get(f"/api/v1/admin/hotels/{hotel.id}/overview", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["hotel"]["id"] == str(hotel.id)
    assert body["stats"]["paid_orders"] == 1 and body["stats"]["completed"] == 1
    assert body["flags"] == []
    assert body["recent_orders"][0]["status"] == "delivered"


async def test_overview_flags_missing_pin_unfinished_orders_and_rejections(client, db):
    headers = await admin_headers(db)
    hotel = await make_hotel(db)  # no location
    for _ in range(4):
        paid(await make_order(db, hotel), "accepted", hours_ago=6)  # paid, never finished
    for _ in range(8):
        paid(await make_order(db, hotel), "rejected")
    await db.flush()
    body = (await client.get(f"/api/v1/admin/hotels/{hotel.id}/overview", headers=headers)).json()
    titles = [f["title"] for f in body["flags"]]
    assert "No map location" in titles
    assert "Paid orders left unfinished" in titles
    assert "Many paid orders rejected or cancelled" in titles
    assert body["flags"][0]["level"] == "high"


async def test_only_the_owner_can_open_it(client, db):
    hotel = await make_hotel(db)
    staff = auth_header(await make_user(db, "hotel_admin", hotel))
    r = await client.get(f"/api/v1/admin/hotels/{hotel.id}/overview", headers=staff)
    assert r.status_code == 403
    r = await client.get(f"/api/v1/admin/hotels/{hotel.id}/overview")
    assert r.status_code in (401, 403)
