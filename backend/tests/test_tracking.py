"""D25: dispatch knows when a rider is free again. D27: rider live location and job trails."""

from datetime import timedelta

from sqlalchemy import func, select

from app.core.time import utcnow
from app.models import RiderPing, RiderProfile
from app.services import tracking
from tests.factories import auth_header, make_user
from tests.test_delivery import API, _hotel, make_rider, ready_delivery


async def deliver(client, db, order, rider):
    h = auth_header(rider)
    staff = auth_header(await make_user(db, "cashier", await _hotel(db, order)))
    await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=h)
    await client.post(f"{API}/hotel/orders/{order.id}/handed-to-rider", headers=staff)
    await client.post(
        f"{API}/rider/jobs/{order.id}/picked-up", headers=h, json={"fee_received": True}
    )
    await client.post(f"{API}/rider/jobs/{order.id}/on-the-way", headers=h)
    return h


async def test_dispatch_shows_rider_free_after_delivery(client, db):
    order = await ready_delivery(db)
    rider = await make_rider(db)
    admin = auth_header(await make_user(db, "super_admin"))
    h = await deliver(client, db, order, rider)

    board = (await client.get(f"{API}/admin/dispatch", headers=admin)).json()
    [me] = [r for r in board["riders"] if r["id"] == str(rider.id)]
    assert me["active_jobs"] == 1 and me["last_code"] is None

    r = await client.post(
        f"{API}/rider/jobs/{order.id}/delivered", headers=h, json={"code": order.delivery_code}
    )
    assert r.json()["status"] == "delivered"

    board = (await client.get(f"{API}/admin/dispatch", headers=admin)).json()
    [me] = [r for r in board["riders"] if r["id"] == str(rider.id)]
    assert (me["active_jobs"], me["is_online"], me["last_code"], me["last_status"]) == (
        0,
        True,
        order.code,
        "delivered",
    )
    [done] = [f for f in board["finished"] if f["id"] == str(order.id)]
    assert (
        done["rider_name"] == rider.name and done["status"] == "delivered" and done["picked_up_at"]
    )
    assert all(o["id"] != str(order.id) for o in board["orders"])


async def test_location_only_while_online(client, db):
    rider = await make_rider(db, online=False)
    h = auth_header(rider)
    r = await client.post(f"{API}/rider/location", headers=h, json={"lat": 0.5636, "lng": 34.5606})
    assert r.status_code == 409 and r.json()["error"]["code"] == "offline"
    pending = await make_rider(db, status="pending", online=False)
    r = await client.post(
        f"{API}/rider/location", headers=auth_header(pending), json={"lat": 0.5, "lng": 34.5}
    )
    assert r.status_code in (403, 409)
    bad = await client.post(f"{API}/rider/location", headers=h, json={"lat": 120, "lng": 34.5})
    assert bad.status_code == 422


async def test_location_on_dispatch_map_and_trail(client, db):
    order = await ready_delivery(db)
    rider = await make_rider(db)
    admin = auth_header(await make_user(db, "super_admin"))
    h = await deliver(client, db, order, rider)

    r = await client.post(
        f"{API}/rider/location",
        headers=h,
        json={"lat": 0.56361234, "lng": 34.5606, "accuracy_m": 12},
    )
    assert r.status_code == 204
    board = (await client.get(f"{API}/admin/dispatch", headers=admin)).json()
    [me] = [x for x in board["riders"] if x["id"] == str(rider.id)]
    assert (me["lat"], me["lng"], me["accuracy_m"], me["live"]) == (0.563612, 34.5606, 12, True)
    [job] = [o for o in board["orders"] if o["id"] == str(order.id)]
    assert job["lat"] == order.lat and "hotel_lat" in job

    trail = (await client.get(f"{API}/admin/dispatch/{order.id}/trail", headers=admin)).json()
    assert len(trail) == 1 and trail[0]["accuracy_m"] == 12
    # Riders can't read trails.
    assert (
        await client.get(f"{API}/admin/dispatch/{order.id}/trail", headers=h)
    ).status_code == 403


async def test_trail_is_throttled_and_pruned(db):
    order = await ready_delivery(db)
    rider = await make_rider(db)
    order.rider_id = rider.id
    await db.flush()
    t0 = utcnow()
    for s in (0, 5, 10, 25):  # every 5 s; only 0 and 25 are 20 s apart
        await tracking.record(
            db, rider.id, lat=0.56, lng=34.56, accuracy_m=None, now=t0 + timedelta(seconds=s)
        )
    n = await db.scalar(
        select(func.count()).select_from(RiderPing).where(RiderPing.order_id == order.id)
    )
    assert n == 2
    assert await tracking.prune(db, t0 + timedelta(days=31)) >= 2


async def test_stale_location_is_not_live(db):
    rider = await make_rider(db)
    await tracking.record(
        db, rider.id, lat=0.56, lng=34.56, accuracy_m=None, now=utcnow() - timedelta(minutes=10)
    )
    p = await db.get(RiderProfile, rider.id)
    assert not tracking.is_live(p, utcnow())
    # No job: the position is kept, but no trail.
    assert (
        await db.scalar(
            select(func.count()).select_from(RiderPing).where(RiderPing.rider_id == rider.id)
        )
        == 0
    )
