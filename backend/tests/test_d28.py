"""D28: password reset, owner creates hotels, eat-in orders, ratings, rough GPS fixes."""

from datetime import timedelta

from sqlalchemy import select

from app.api.v1 import ordering
from app.core.time import utcnow
from app.models import Order, RiderProfile
from app.services import tracking
from tests.factories import PASSWORD, auth_header, make_hotel, make_order, make_user
from tests.test_ordering import NOW, body, key, open_hotel

API = "/api/v1"


async def _login(client, user, password):
    return await client.post(f"{API}/auth/login", json={"phone": user.phone, "password": password})


# --- Passwords ----------------------------------------------------------------------------------


async def test_admin_reset_then_forced_change(client, db):
    admin = await make_user(db, "super_admin")
    rider = await make_user(db, "rider")
    old = (await _login(client, rider, PASSWORD)).json()

    r = await client.post(
        f"{API}/admin/users/{rider.id}/reset-password", headers=auth_header(admin)
    )
    assert r.status_code == 200, r.text
    temp = r.json()["temp_password"]
    assert (await _login(client, rider, PASSWORD)).status_code == 401
    # Every open session was logged out.
    refreshed = await client.post(
        f"{API}/auth/refresh", json={"refresh_token": old["refresh_token"]}
    )
    assert refreshed.status_code == 401

    login = (await _login(client, rider, temp)).json()
    assert login["user"]["must_change_password"] is True
    hdr = {"Authorization": f"Bearer {login['access_token']}"}
    bad = await client.post(
        f"{API}/auth/change-password",
        headers=hdr,
        json={"current_password": "nope", "new_password": "a-brand-new-one"},
    )
    assert bad.status_code == 400
    ok = await client.post(
        f"{API}/auth/change-password",
        headers=hdr,
        json={"current_password": temp, "new_password": "a-brand-new-one"},
    )
    assert ok.status_code == 200 and ok.json()["user"]["must_change_password"] is False
    assert (await _login(client, rider, "a-brand-new-one")).status_code == 200


async def test_hotel_admin_manages_only_own_cashiers(client, db):
    hotel, other = await make_hotel(db), await make_hotel(db)
    boss = await make_user(db, "hotel_admin", hotel)
    mine = await make_user(db, "cashier", hotel)
    theirs = await make_user(db, "cashier", other)
    hdr = auth_header(boss)

    staff = (await client.get(f"{API}/hotel/staff", headers=hdr)).json()
    assert {s["id"] for s in staff} == {str(boss.id), str(mine.id)}
    assert (
        await client.post(f"{API}/hotel/staff/{mine.id}/reset-password", headers=hdr)
    ).status_code == 200
    assert (
        await client.post(f"{API}/hotel/staff/{theirs.id}/reset-password", headers=hdr)
    ).status_code == 404
    assert (
        await client.post(f"{API}/hotel/staff/{boss.id}/reset-password", headers=hdr)
    ).status_code == 404
    # A cashier can't do it at all.
    r = await client.post(f"{API}/hotel/staff/{mine.id}/reset-password", headers=auth_header(mine))
    assert r.status_code == 403

    added = await client.post(
        f"{API}/hotel/staff",
        headers=hdr,
        json={"name": "New Cashier", "phone": "0711999888", "password": "first-pass-123"},
    )
    assert added.status_code == 201 and added.json()["role"] == "cashier"


# --- Owner creates hotels -----------------------------------------------------------------------


async def test_owner_creates_hotel_with_admin_login(client, db):
    admin = await make_user(db, "super_admin")
    r = await client.post(
        f"{API}/admin/hotels",
        headers=auth_header(admin),
        json={
            "name": "Mama Oliech",
            "slug": "mama-oliech",
            "phone": "0722000111",
            "till_number": "5123456",
            "lat": -1.283333,
            "lng": 36.816667,
            "admin": {"name": "Jane Owner", "phone": "0722000222", "password": "start-here-1"},
        },
    )
    assert r.status_code == 201, r.text
    login = await client.post(
        f"{API}/auth/login", json={"phone": "0722000222", "password": "start-here-1"}
    )
    me = login.json()["user"]
    assert (me["role"], me["hotel_id"], me["must_change_password"]) == (
        "hotel_admin",
        r.json()["id"],
        True,
    )
    hotel_admin = await make_user(db, "hotel_admin", await make_hotel(db))
    denied = await client.post(f"{API}/admin/hotels", headers=auth_header(hotel_admin), json={})
    assert denied.status_code == 403


# --- Eat in -------------------------------------------------------------------------------------


def eat_in(hotel, product, arrive=NOW + timedelta(minutes=45), **kw):
    data = body(
        hotel,
        product,
        type="eat_in",
        rider_fee_mode="none",
        arrive_at=arrive.isoformat(),
        expected_total=650 + 20 + 30,
        **kw,
    )
    for k in ("lat", "lng", "landmark"):
        data.pop(k)
    return data


async def test_eat_in_quote_and_order(client, db, monkeypatch):
    monkeypatch.setattr(ordering, "utcnow", lambda: NOW)
    hotel, product = await open_hotel(db)
    q = await client.post(
        f"{API}/quotes",
        json={
            "hotel_slug": hotel.slug,
            "lines": [{"product_id": str(product.id), "quantity": 1}],
            "type": "eat_in",
            "rider_fee_mode": "none",
        },
    )
    assert q.status_code == 200, q.text
    q = q.json()
    assert (q["rider_fee"], q["eat_in_fee"], q["service_fee"], q["till_amount"]) == (0, 30, 50, 700)

    r = await client.post(f"{API}/orders", json=eat_in(hotel, product), headers=key())
    assert r.status_code == 201, r.text
    order = await db.scalar(select(Order).where(Order.code == r.json()["code"]))
    assert (order.type, order.eat_in_fee, order.till_amount, order.lat) == ("eat_in", 30, 700, None)
    assert order.arrive_at == NOW + timedelta(minutes=45)

    too_soon = eat_in(hotel, product, arrive=NOW + timedelta(minutes=2))
    r = await client.post(f"{API}/orders", json=too_soon, headers=key())
    assert (r.status_code, r.json()["error"]["code"]) == (422, "bad_arrival")


async def test_eat_in_rules(client, db):
    hotel, product = await open_hotel(db)
    no_time = eat_in(hotel, product)
    no_time.pop("arrive_at")
    assert (await client.post(f"{API}/orders", json=no_time, headers=key())).status_code == 422
    cash = eat_in(hotel, product, payment_method="cash")
    assert (await client.post(f"{API}/orders", json=cash, headers=key())).status_code == 422


async def test_eat_in_order_is_collected_like_pickup(client, db):
    hotel = await make_hotel(db)
    staff = await make_user(db, "hotel_admin", hotel)
    order = await make_order(db, hotel, order_type="pickup", rider_fee_mode="none", status="ready")
    order.type, order.arrive_at = "eat_in", utcnow() + timedelta(minutes=30)
    await db.flush()
    r = await client.post(f"{API}/hotel/orders/{order.id}/collected", headers=auth_header(staff))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "collected"


# --- Ratings ------------------------------------------------------------------------------------


async def test_rating_once_after_finishing_and_ranking(client, db):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel, order_type="pickup", rider_fee_mode="none")
    url = f"{API}/track/{order.tracking_token}/rating"
    assert (await client.post(url, json={"hotel_stars": 5})).status_code == 409  # not finished
    order.status = "collected"
    await db.flush()
    assert (await client.get(f"{API}/track/{order.tracking_token}")).json()["can_rate"] is True
    assert (await client.post(url, json={"hotel_stars": 6})).status_code == 422
    assert (
        await client.post(url, json={"hotel_stars": 5, "comment": " Tamu sana "})
    ).status_code == 204
    assert (await client.post(url, json={"hotel_stars": 1})).status_code == 409
    track = (await client.get(f"{API}/track/{order.tracking_token}")).json()
    assert (track["rated"], track["can_rate"]) == (True, False)

    listed = {h["slug"]: h for h in (await client.get(f"{API}/hotels")).json()}
    assert (listed[hotel.slug]["rating"], listed[hotel.slug]["rating_count"]) == (5.0, 1)


async def test_delivery_rating_needs_rider_stars(client, db):
    hotel = await make_hotel(db)
    rider = await make_user(db, "rider")
    order = await make_order(db, hotel, status="delivered")
    order.rider_id = rider.id
    await db.flush()
    url = f"{API}/track/{order.tracking_token}/rating"
    assert (await client.post(url, json={"hotel_stars": 4})).status_code == 422
    assert (await client.post(url, json={"hotel_stars": 4, "rider_stars": 3})).status_code == 204


# --- Rough GPS ----------------------------------------------------------------------------------


async def test_rough_gps_fix_keeps_last_good_position(db):
    rider = await make_user(db, "rider")
    db.add(
        RiderProfile(
            user_id=rider.id,
            national_id="12345678",
            mpesa_number=rider.phone,
            next_of_kin="Kin",
            kyc_status="draft",
        )
    )
    await db.flush()
    p = await db.get(RiderProfile, rider.id)
    p.kyc_status, p.is_online = "approved", True
    p.id_front_key = p.id_back_key = p.selfie_key = "x"
    p.consent_at = utcnow()
    await db.flush()
    now = utcnow()
    await tracking.record(db, rider.id, lat=-1.28, lng=36.82, accuracy_m=12, now=now)
    await tracking.record(
        db, rider.id, lat=-1.40, lng=36.95, accuracy_m=900, now=now + timedelta(seconds=30)
    )
    assert (p.last_lat, p.last_lng) == (-1.28, 36.82)
    assert p.last_seen_at == now + timedelta(seconds=30)
    # Much later with nothing better, the rough fix is still used.
    later = now + timedelta(minutes=10)
    await tracking.record(db, rider.id, lat=-1.40, lng=36.95, accuracy_m=900, now=later)
    assert (p.last_lat, p.last_lng) == (-1.40, 36.95)
