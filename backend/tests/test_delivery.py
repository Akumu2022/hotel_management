"""M6 acceptance: riders claim or are assigned deliveries; the delivery code proves the handover;
rider fees follow the spec's table; D7 failed deliveries and D8 unpaid fees."""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.time import utcnow
from app.models import Customer, LedgerEntry, Order, ReviewItem, RiderProfile, User
from app.services import delivery, order_flow, payments
from tests.factories import auth_header, make_hotel, make_order, make_user

API = "/api/v1"


async def make_rider(db, *, payout="instant", online=True, status="approved", phone=None) -> User:
    user = await make_user(db, "rider")
    if phone:
        user.phone = phone
    db.add(
        RiderProfile(
            user_id=user.id,
            national_id=user.phone[-8:],
            mpesa_number=user.phone,
            next_of_kin="Nafula Barasa",
            next_of_kin_phone="254700000009",
            residence_area="Kanduyi",
            id_front_key="k/f.webp",
            id_back_key="k/b.webp",
            selfie_key="k/s.webp",
            consent_at=utcnow(),
            kyc_status=status,
            payout_mode=payout,
            is_online=online,
        )
    )
    await db.flush()
    return user


async def ready_delivery(db, hotel=None, *, mode="included", accept_only=False) -> Order:
    hotel = hotel or await make_hotel(db)
    order = await make_order(db, hotel, rider_fee_mode=mode)
    cashier = await make_user(db, "cashier", hotel)
    await payments.confirm_manual(
        db,
        order.id,
        code=f"SJK{order.code[:7]}",
        amount=order.till_amount,
        paid_at=None,
        cashier_id=cashier.id,
        now=utcnow(),
    )
    kw = {"user_id": cashier.id, "hotel_id": hotel.id, "now": utcnow()}
    await order_flow.accept(db, order.id, prep_minutes=15, **kw)
    if not accept_only:
        await order_flow.preparing(db, order.id, **kw)
        await order_flow.ready(db, order.id, **kw)
    return order


async def pick_up(client, db, order, rider_headers):
    """Hotel hands the food over with the rider's pickup PIN (the rider can't self-confirm)."""
    await db.refresh(order)
    staff = auth_header(await make_user(db, "cashier", await _hotel(db, order)))
    r = await client.post(
        f"{API}/hotel/orders/{order.id}/handed-to-rider",
        headers=staff,
        json={"pin": delivery.pickup_pin(order)},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def entries(db, order_id) -> dict[str, int]:
    rows = (await db.execute(select(LedgerEntry).where(LedgerEntry.order_id == order_id))).scalars()
    out: dict[str, int] = {}
    for r in rows:
        out[r.entry_type] = out.get(r.entry_type, 0) + r.amount
    return out


# --- Dispatch ------------------------------------------------------------------------------------


async def test_open_jobs_hide_customer_until_claimed(client, db):
    order = await ready_delivery(db, accept_only=True)
    h = auth_header(await make_rider(db))
    jobs = (await client.get(f"{API}/rider/jobs", headers=h)).json()
    job = next(j for j in jobs if j["id"] == str(order.id))
    assert job["customer_phone"] is None and job["lat"] is None and job["mine"] is False
    assert job["rider_fee"] == 100 and job["fee_with_food"] is True
    assert "delivery_code" not in job

    r = await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=h)
    assert r.status_code == 200 and r.json()["mine"] is True
    phone, name, land = (r.json()[k] for k in ("customer_phone", "customer_name", "landmark"))
    assert phone is None and name and land is None


async def test_second_rider_cannot_take_a_taken_job(client, db):
    order = await ready_delivery(db)
    a, b = auth_header(await make_rider(db)), auth_header(await make_rider(db))
    assert (await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=a)).status_code == 200
    r = await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=b)
    assert r.status_code == 409 and r.json()["error"]["code"] == "job_taken"
    assert (await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=a)).status_code == 200


async def test_claim_race_one_winner(committed):
    async with committed() as s:
        order = await ready_delivery(s)
        riders_ = [await make_rider(s) for _ in range(5)]
        await s.commit()

    async def attempt(rider):
        async with committed() as s:
            try:
                await delivery.claim(s, order.id, rider.id, utcnow())
                await s.commit()
                return True
            except Exception:
                await s.rollback()
                return False

    results = await asyncio.gather(*(attempt(r) for r in riders_))
    assert results.count(True) == 1
    async with committed() as s:
        assert (await s.get(Order, order.id)).rider_id in {r.id for r in riders_}


@pytest.mark.parametrize(
    ("status", "online", "code"), [("pending", True, 403), ("approved", False, 409)]
)
async def test_unapproved_or_offline_rider_cannot_claim(client, db, status, online, code):
    order = await ready_delivery(db)
    h = auth_header(await make_rider(db, status=status, online=online))
    assert (await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=h)).status_code == code


async def test_admin_assigns_and_reassigns(client, db):
    order = await ready_delivery(db)
    r1, r2 = await make_rider(db), await make_rider(db, online=False)
    admin = auth_header(await make_user(db, "super_admin"))
    for rider in (r1, r2):
        r = await client.post(
            f"{API}/admin/dispatch/{order.id}/assign",
            headers=admin,
            json={"rider_id": str(rider.id)},
        )
        assert r.status_code == 200 and r.json()["rider_id"] == str(rider.id)
    board = (await client.get(f"{API}/admin/dispatch", headers=admin)).json()
    row = next(o for o in board["orders"] if o["id"] == str(order.id))
    assert row["rider_name"] == r2.name
    assert {x["id"] for x in board["riders"]} >= {str(r1.id), str(r2.id)}


# --- Option A instant: hotel and rider both confirm ----------------------------------------------


async def test_option_a_instant_full_delivery(client, db):
    order = await ready_delivery(db)
    rider = await make_rider(db)
    h = auth_header(rider)
    staff = auth_header(await make_user(db, "cashier", await _hotel(db, order)))
    await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=h)

    await db.refresh(order)
    card = (
        await client.post(
            f"{API}/hotel/orders/{order.id}/handed-to-rider",
            headers=staff,
            json={"pin": delivery.pickup_pin(order)},
        )
    ).json()
    assert (card["status"], card["fee_with_food"], card["fee_handed"]) == ("picked_up", True, True)
    assert "rider_fee_instant" not in await entries(db, order.id)  # rider hasn't confirmed yet
    r = await client.post(
        f"{API}/rider/jobs/{order.id}/picked-up", headers=h, json={"fee_received": True}
    )
    assert r.json()["fee_rider_confirmed"] is True
    assert (await entries(db, order.id))["rider_fee_instant"] == 100

    t = (await client.get(f"{API}/track/{order.tracking_token}")).json()
    assert t["rider_name"] == rider.name.split(" ")[0] and t["rider_phone"] == rider.phone

    await client.post(f"{API}/rider/jobs/{order.id}/on-the-way", headers=h)
    r = await client.post(
        f"{API}/rider/jobs/{order.id}/delivered",
        headers=h,
        json={"code": "0000" if order.delivery_code != "0000" else "1111"},
    )
    assert r.status_code == 422 and "4 tries left" in r.json()["error"]["message"]
    r = await client.post(
        f"{API}/rider/jobs/{order.id}/delivered", headers=h, json={"code": order.delivery_code}
    )
    assert r.json()["status"] == "delivered"
    await db.refresh(order)
    assert order.delivery_code_attempts == 1  # the wrong try was kept
    assert (await db.get(Customer, order.customer_phone)).completed_orders == 1


async def _hotel(db, order):
    from app.models import Hotel

    return await db.get(Hotel, order.hotel_id)


async def test_rider_says_fee_not_handed_over_goes_to_admin(client, db):
    order = await ready_delivery(db)
    h = auth_header(await make_rider(db))
    await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=h)
    await pick_up(client, db, order, h)
    await client.post(
        f"{API}/rider/jobs/{order.id}/picked-up", headers=h, json={"fee_received": False}
    )
    item = (
        await db.execute(select(ReviewItem).where(ReviewItem.order_id == order.id))
    ).scalar_one()
    assert item.type == "fee_dispute"
    staff = auth_header(await make_user(db, "cashier", await _hotel(db, order)))
    assert (
        await client.get(f"{API}/hotel/review-items", headers=staff)
    ).json() == []  # admin's, not the hotel's
    admin = auth_header(await make_user(db, "super_admin"))
    r = await client.post(
        f"{API}/admin/review-items/{item.id}/resolve", headers=admin, json={"action": "pay_rider"}
    )
    assert r.status_code == 200, r.text
    e = await entries(db, order.id)
    assert (e["rider_fee_held"], e["rider_fee_owed"]) == (100, 100)  # settled via statements


async def test_option_a_weekly_rider(client, db):
    order = await ready_delivery(db)
    h = auth_header(await make_rider(db, payout="weekly"))
    await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=h)
    await pick_up(client, db, order, h)
    job = (await client.post(f"{API}/rider/jobs/{order.id}/picked-up", headers=h, json={})).json()
    assert job["fee_with_food"] is False
    await client.post(
        f"{API}/rider/jobs/{order.id}/delivered", headers=h, json={"code": order.delivery_code}
    )
    e = await entries(db, order.id)
    assert (e["rider_fee_held"], e["rider_fee_owed"]) == (100, 100) and "rider_fee_instant" not in e


async def test_code_locks_after_five_wrong_tries(client, db):
    order = await ready_delivery(db)
    h = auth_header(await make_rider(db))
    await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=h)
    await pick_up(client, db, order, h)
    wrong = "0000" if order.delivery_code != "0000" else "1111"
    for _ in range(5):
        await client.post(f"{API}/rider/jobs/{order.id}/delivered", headers=h, json={"code": wrong})
    r = await client.post(
        f"{API}/rider/jobs/{order.id}/delivered", headers=h, json={"code": order.delivery_code}
    )
    assert r.status_code == 423
    assert (
        await db.execute(select(ReviewItem.type).where(ReviewItem.order_id == order.id))
    ).scalar_one() == "failed_delivery"


# --- Option B and D8 ------------------------------------------------------------------------------


async def deliver_cash(client, db, **kw):
    order = await ready_delivery(db, mode="cash")
    rider = await make_rider(db)
    h = auth_header(rider)
    await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=h)
    await pick_up(client, db, order, h)
    r = await client.post(
        f"{API}/rider/jobs/{order.id}/delivered",
        headers=h,
        json={"code": order.delivery_code, **kw},
    )
    assert r.status_code == 200, r.text
    return order, h


async def test_option_b_fee_received(client, db):
    order, _ = await deliver_cash(client, db, cash_fee_received=True)
    assert (await entries(db, order.id))["rider_fee_cash"] == 100


async def test_option_b_fee_not_paid_customer_says_no(client, db):
    order, h = await deliver_cash(client, db)
    r = await client.post(f"{API}/rider/jobs/{order.id}/fee-not-paid", headers=h)
    assert r.json()["fee_not_paid"] is True
    t = (await client.get(f"{API}/track/{order.tracking_token}")).json()
    assert t["fee_question"] is True
    await client.post(f"{API}/track/{order.tracking_token}/rider-fee-answer", json={"paid": False})
    assert (await entries(db, order.id))["rider_compensation"] == 100
    c = await db.get(Customer, order.customer_phone)
    assert (c.option_b_blocked, c.blocklisted) == (True, False)


async def test_option_b_customer_says_paid_goes_to_admin(client, db):
    order, h = await deliver_cash(client, db)
    await client.post(f"{API}/rider/jobs/{order.id}/fee-not-paid", headers=h)
    await client.post(f"{API}/track/{order.tracking_token}/rider-fee-answer", json={"paid": True})
    assert "rider_compensation" not in await entries(db, order.id)
    item = (
        await db.execute(select(ReviewItem).where(ReviewItem.order_id == order.id))
    ).scalar_one()
    assert item.type == "fee_dispute"


async def test_no_answer_in_24h_counts_as_no(client, db):
    order, h = await deliver_cash(client, db)
    await client.post(f"{API}/rider/jobs/{order.id}/fee-not-paid", headers=h)
    assert await delivery.answer_timeouts(db, utcnow() + timedelta(hours=1)) == 0
    assert await delivery.answer_timeouts(db, utcnow() + timedelta(hours=25)) == 1
    assert (await entries(db, order.id))["rider_compensation"] == 100
    assert (await entries(db, order.id))["rider_compensation"] == 100


async def test_fee_not_paid_needs_a_delivered_cash_order(client, db):
    order, h = await deliver_cash(client, db, cash_fee_received=True)
    r = await client.post(f"{API}/rider/jobs/{order.id}/fee-not-paid", headers=h)
    assert r.status_code == 409  # already confirmed as received


# --- D7 failed delivery ---------------------------------------------------------------------------


async def failed(client, db, rider=None):
    order = await ready_delivery(db)
    rider = rider or await make_rider(db)
    h = auth_header(rider)
    await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=h)
    await pick_up(client, db, order, h)
    r = await client.post(
        f"{API}/rider/jobs/{order.id}/failed",
        headers=h,
        json={"reason": "accident", "note": "Fell near the stage"},
    )
    assert r.json()["status"] == "failed_delivery"
    item = (
        await db.execute(select(ReviewItem).where(ReviewItem.order_id == order.id))
    ).scalar_one()
    return order, rider, item


async def test_rider_fault_refunds_credits_hotel_and_strikes(client, db):
    admin = auth_header(await make_user(db, "super_admin"))
    order, rider, item = await failed(client, db)
    r = await client.post(
        f"{API}/admin/review-items/{item.id}/resolve", headers=admin, json={"action": "rider_fault"}
    )
    assert r.status_code == 200, r.text
    e = await entries(db, order.id)
    assert e["failed_delivery_credit"] == 770  # platform makes the hotel whole
    assert "rider_fee_instant" not in e and "rider_fee_held" not in e  # rider earns nothing
    assert (await db.get(RiderProfile, rider.id)).kyc_status == "approved"  # one strike

    _, _, item2 = await failed(client, db, rider)
    await client.post(
        f"{API}/admin/review-items/{item2.id}/resolve",
        headers=admin,
        json={"action": "rider_fault"},
    )
    p = await db.get(RiderProfile, rider.id)
    assert (p.kyc_status, p.kyc_note) == ("suspended", "Two failed deliveries in 30 days")


async def test_customer_fault_no_refund_rider_paid(client, db):
    admin = auth_header(await make_user(db, "super_admin"))
    order, _, item = await failed(client, db)
    await client.post(
        f"{API}/admin/review-items/{item.id}/resolve",
        headers=admin,
        json={"action": "customer_fault"},
    )
    e = await entries(db, order.id)
    assert "refund" not in e and e["rider_fee_held"] == 100  # fee never handed over -> weekly
    assert (await db.get(Customer, order.customer_phone)).option_b_blocked is True


# --- Pickup PIN: ten riders at one hotel -----------------------------------------------------------


async def test_pickup_pin_gates_the_handover(client, db):
    order = await ready_delivery(db)
    rider = await make_rider(db)
    h = auth_header(rider)
    staff = auth_header(await make_user(db, "cashier", await _hotel(db, order)))
    other = auth_header(await make_rider(db))
    await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=h)
    await db.refresh(order)
    pin = delivery.pickup_pin(order)

    # The assigned rider sees the PIN and not the customer's number; other riders see neither.
    mine = next(j for j in (await client.get(f"{API}/rider/jobs", headers=h)).json() if j["mine"])
    assert mine["pickup_pin"] == pin and mine["customer_phone"] is None
    others = (await client.get(f"{API}/rider/jobs", headers=other)).json()
    assert all(j["pickup_pin"] is None for j in others)

    # The rider can't confirm the pickup themselves.
    r = await client.post(f"{API}/rider/jobs/{order.id}/picked-up", headers=h, json={})
    assert (r.status_code, r.json()["error"]["code"]) == (409, "pin_required")

    # The hotel needs the right PIN.
    url = f"{API}/hotel/orders/{order.id}/handed-to-rider"
    no_pin = await client.post(url, headers=staff)
    assert no_pin.status_code == 403
    wrong = "0000" if pin != "0000" else "1111"
    bad = await client.post(url, headers=staff, json={"pin": wrong})
    assert (bad.status_code, bad.json()["error"]["code"]) == (403, "wrong_pin")
    await db.refresh(order)
    assert order.status == "ready"

    ok = await client.post(url, headers=staff, json={"pin": pin})
    assert ok.status_code == 200 and ok.json()["status"] == "picked_up"
    again = await client.post(url, headers=staff)  # a retry after success is harmless
    assert again.status_code == 200

    # Once the food is collected the customer's number opens and the PIN is gone.
    mine = next(j for j in (await client.get(f"{API}/rider/jobs", headers=h)).json() if j["mine"])
    assert mine["customer_phone"] and mine["pickup_pin"] is None


async def test_pickup_pin_is_per_rider_and_per_order(client, db):
    a, b = await ready_delivery(db), await ready_delivery(db)
    r1 = await make_rider(db)
    for o in (a, b):
        await client.post(f"{API}/rider/jobs/{o.id}/claim", headers=auth_header(r1))
    await db.refresh(a)
    await db.refresh(b)
    assert delivery.pickup_pin(a) and delivery.pickup_pin(b)  # one PIN per order and rider
    # An order nobody has taken has no PIN.
    c = await ready_delivery(db)
    assert delivery.pickup_pin(c) is None


async def test_rider_summary_groups_and_pages_their_orders(client, db):
    order = await ready_delivery(db)
    rider = await make_rider(db)
    h = auth_header(rider)
    first = (await client.get(f"{API}/rider/summary", headers=h)).json()
    assert first["orders"] == [] and first["open_now"] >= 1 and first["has_more"] is False
    assert first["counts"]["waiting"] == 0

    assert (await client.post(f"{API}/rider/jobs/{order.id}/claim", headers=h)).status_code == 200
    got = (await client.get(f"{API}/rider/summary?period=today", headers=h)).json()
    assert [(o["code"], o["group"]) for o in got["orders"]] == [(order.code, "waiting")]
    assert got["counts"]["waiting"] == 1

    row = await db.get(Order, order.id)
    row.status = "failed_delivery"
    row.closed_at = utcnow()
    await db.commit()
    got = (await client.get(f"{API}/rider/summary?period=all", headers=h)).json()
    assert got["orders"][0]["group"] == "failed" and got["counts"]["failed"] == 1
    only = (await client.get(f"{API}/rider/summary?period=all&group=delivered", headers=h)).json()
    assert only["orders"] == [] and only["counts"]["failed"] == 1
    old = row.closed_at = utcnow() - timedelta(days=40)
    await db.commit()
    month = (await client.get(f"{API}/rider/summary?period=month", headers=h)).json()
    assert month["counts"]["failed"] == 0 and old
    other = auth_header(await make_rider(db))
    assert (await client.get(f"{API}/rider/summary", headers=other)).json()["orders"] == []


async def test_dispatch_lists_riders_nearest_to_the_pickup_first(client, db, monkeypatch):
    from app.models import RiderProfile
    from app.services import routing

    hotel = await make_hotel(db, lat=0.5636, lng=34.5606)
    order = await ready_delivery(db, hotel)
    admin = auth_header(await make_user(db, "super_admin"))
    near, far, silent = await make_rider(db), await make_rider(db), await make_rider(db)
    for rider, (la, lo) in ((near, (0.5640, 34.5610)), (far, (0.6000, 34.6000))):
        p = await db.get(RiderProfile, rider.id)
        p.last_lat, p.last_lng, p.last_location_at = la, lo, utcnow()
    await db.flush()

    async def trips(starts, lat, lng):  # as if the road were twice the straight line
        return [routing.Trip(km=round(i + 1.0, 1), minutes=(i + 1) * 4, method="road") for i, _ in enumerate(starts)]

    monkeypatch.setattr(routing, "trips_to", trips)
    r = await client.get(f"/api/v1/admin/dispatch/{order.id}/nearest", headers=admin)
    assert r.status_code == 200, r.text
    ids = [x["rider_id"] for x in r.json()]
    assert str(silent.id) not in ids  # no recent position: not ranked
    assert set(ids) == {str(near.id), str(far.id)}
    assert [x["minutes"] for x in r.json()] == sorted(x["minutes"] for x in r.json())


async def test_trips_fall_back_to_a_straight_line_estimate_when_routing_is_down(monkeypatch):
    import httpx

    from app.services import routing

    class Down:
        async def __aenter__(self):
            raise httpx.ConnectError("down")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(routing.httpx, "AsyncClient", lambda **kw: Down())
    out = await routing.trips_to([(0.5640, 34.5610), (0.6000, 34.6000)], 0.5636, 34.5606)
    assert [t.method for t in out] == ["estimated", "estimated"]
    assert out[0].minutes >= 1 and out[1].km > out[0].km
