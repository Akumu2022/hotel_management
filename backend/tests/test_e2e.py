"""End-to-end journeys across every role, through the HTTP API (DECISIONS D23).

Each journey also checks the alarm signals: the same counts the screens use to decide whether to
ring (web/src/lib/alarm.ts). An alarm must start when something needs doing and stop by itself
as soon as the right action is done, by anyone, on any device; there is no "silence" button.

Hotels are treated as open at midday Kenya time (only the opening-hours check is pinned); every
other rule runs on the real clock. Payments arrive as real Till SMS text, as the SMS app will
send them.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.time import utcnow
from app.models import Customer, Hotel, LedgerEntry, Order, RiderProfile
from app.services import hours, jobs, order_flow, orders
from tests.factories import auth_header, make_user
from tests.test_delivery import make_rider
from tests.test_ordering import INSIDE, ZONE, open_hotel

API = "/api/v1"
EAT = timedelta(hours=3)


# --- World ---------------------------------------------------------------------------------------


@dataclass
class World:
    hotel: Hotel
    product_id: str
    cashier: dict
    owner: dict  # hotel admin
    admin: dict  # super admin
    r1: dict
    r2: dict
    r1_id: uuid.UUID
    r2_id: uuid.UUID


@pytest.fixture(autouse=True)
def hotels_open_at_midday(monkeypatch):
    real = hours.open_status

    def at_noon(hotel, hotel_hours, now, cutoff):
        local_noon = (now + EAT).replace(hour=12, minute=0, second=0, microsecond=0) - EAT
        return real(hotel, hotel_hours, local_noon, cutoff)

    monkeypatch.setattr(orders.hours, "open_status", at_noon)


@pytest.fixture
async def w(db, client):
    from app.services import settings

    hotel, product = await open_hotel(db)
    await settings.update(db, {"delivery_zone": ZONE}, None)
    r1, r2 = await make_rider(db), await make_rider(db)
    return World(
        hotel=hotel,
        product_id=str(product.id),
        cashier=auth_header(await make_user(db, "cashier", hotel)),
        owner=auth_header(await make_user(db, "hotel_admin", hotel)),
        admin=auth_header(await make_user(db, "super_admin")),
        r1=auth_header(r1),
        r2=auth_header(r2),
        r1_id=r1.id,
        r2_id=r2.id,
    )


def order_body(
    w: World, kind="delivery", mode="included", pay="mpesa", phone="0712000111", qty=1, **kw
):
    body = {
        "hotel_slug": w.hotel.slug,
        "lines": [{"product_id": w.product_id, "quantity": qty}],
        "type": kind,
        "rider_fee_mode": mode if kind == "delivery" else "none",
        "name": "Mercy Nekesa",
        "phone": phone,
        "payment_method": pay,
        "landmark": "Blue gate next to the school" if kind == "delivery" else None,
        "lat": INSIDE["lat"] if kind == "delivery" else None,
        "lng": INSIDE["lng"] if kind == "delivery" else None,
    }
    body.update(kw)
    return body


async def place(client, w, **kw) -> dict:
    body = order_body(w, **kw)
    quote_body = {
        k: body[k] for k in ("hotel_slug", "lines", "type", "rider_fee_mode", "phone", "lat", "lng")
    }
    q = (await client.post(f"{API}/quotes", json=quote_body)).json()
    r = await client.post(
        f"{API}/orders",
        headers={"Idempotency-Key": uuid.uuid4().hex},
        json={**body, "expected_total": q["till_amount"]},
    )
    assert r.status_code == 201, r.text
    return r.json()


def sms(code: str, amount: int, *, phone="254712000111", at: datetime | None = None) -> str:
    """A Till SMS in the real format (docs/sms_samples)."""
    t = (at or utcnow()) + EAT
    hour = t.strftime("%I").lstrip("0") or "12"
    return (
        f"{code} Confirmed.on {t.day}/{t.month}/{t:%y} at {hour}:{t:%M} {t:%p}"
        f"KSH{amount:,}.00 received from {phone} MERCY NEKESA. New Account balance is KSH9,999.00."
    )


async def till_sms(client, w, code, amount, **kw) -> dict:
    r = await client.post(
        f"{API}/admin/test-sms",
        headers=w.admin,
        json={"till_number": w.hotel.till_number, "raw_text": sms(code, amount, **kw)},
    )
    assert r.status_code == 200, r.text
    return r.json()


def new_code() -> str:
    return "UJ" + uuid.uuid4().hex[:8].upper()


async def order_id(db, code: str) -> uuid.UUID:
    return await db.scalar(select(Order.id).where(Order.code == code))


async def hotel_step(client, w, code, step, body=None, who=None):
    oid = await order_id_from_board(client, w, code)
    r = await client.post(f"{API}/hotel/orders/{oid}/{step}", headers=who or w.cashier, json=body)
    assert r.status_code == 200, r.text
    return r.json()


async def order_id_from_board(client, w, code):
    for view in ("active", "done"):
        for o in (await client.get(f"{API}/hotel/orders?view={view}", headers=w.cashier)).json():
            if o["code"] == code:
                return o["id"]
    pending = (await client.get(f"{API}/hotel/payments/pending", headers=w.cashier)).json()
    return next(o["id"] for o in pending if o["code"] == code)


# --- Alarm signals (mirror of the screens' logic) -------------------------------------------------


async def hotel_alarms(client, w) -> dict:
    board = (await client.get(f"{API}/hotel/orders", headers=w.cashier)).json()
    pending = (await client.get(f"{API}/hotel/payments/pending", headers=w.cashier)).json()
    reviews = (await client.get(f"{API}/hotel/review-items", headers=w.cashier)).json()
    refunds = (await client.get(f"{API}/hotel/refunds", headers=w.cashier)).json()
    return {
        "new_orders": sum(o["status"] in ("paid", "awaiting_payment") for o in board),
        "payments": sum(1 for p in pending if p["customer_trans_code"])
        + len(reviews)
        + len(refunds),
    }


async def rider_alarms(client, headers) -> dict:
    me = (await client.get(f"{API}/rider/me", headers=headers)).json()
    jobs_ = (await client.get(f"{API}/rider/jobs", headers=headers)).json()
    mine = [j for j in jobs_ if j["mine"]]
    open_ = [j for j in jobs_ if not j["mine"]]
    return {
        "open_jobs": len(open_) if me["is_online"] and not mine else 0,
        "assigned_unseen": sum(not j["seen"] for j in mine),
    }


async def admin_alarms(client, w, db, now=None) -> dict:
    now = now or utcnow()
    reviews = (await client.get(f"{API}/admin/review-items", headers=w.admin)).json()
    board = (await client.get(f"{API}/admin/dispatch", headers=w.admin)).json()["orders"]

    def mins(iso):
        return (now - datetime.fromisoformat(iso)).total_seconds() / 60 if iso else 0

    return {
        "unaccepted": len(await order_flow.duty_alerts(db, now)),
        "needs_decision": sum(
            1
            for r in reviews
            if not r["hotel_name"] or r["type"] in ("failed_delivery", "fee_dispute")
        ),
        "no_rider": sum(
            1
            for o in board
            if o["status"] == "ready" and not o["rider_id"] and mins(o["ready_at"]) >= 5
        ),
        "long_delivery": sum(
            1
            for o in board
            if o["status"] in ("picked_up", "on_the_way") and mins(o["picked_up_at"]) >= 45
        ),
    }


async def track(client, token) -> dict:
    return (await client.get(f"{API}/track/{token}")).json()


async def go_online(client, *riders):
    for h in riders:
        assert (
            await client.post(f"{API}/rider/online", headers=h, json={"online": True})
        ).status_code == 200


# --- Journeys ------------------------------------------------------------------------------------


async def test_pickup_paid_by_sms_full_journey(client, db, w):
    o = await place(client, w, kind="pickup")
    assert await hotel_alarms(client, w) == {"new_orders": 0, "payments": 0}  # not paid yet: quiet

    code = new_code()
    await client.post(f"{API}/track/{o['tracking_token']}/payment-code", json={"code": code})
    assert (await hotel_alarms(client, w))["payments"] == 1  # code to confirm: rings

    assert (await till_sms(client, w, code, o["till_amount"]))["result"] == "paid"
    assert await hotel_alarms(client, w) == {
        "new_orders": 1,
        "payments": 0,
    }  # SMS matched: payment alarm stops, order alarm starts

    await hotel_step(client, w, o["code"], "accept", {"prep_minutes": 15})
    assert (await hotel_alarms(client, w))["new_orders"] == 0  # accepted: stops
    for step in ("preparing", "ready", "collected"):
        await hotel_step(client, w, o["code"], step)
    t = await track(client, o["tracking_token"])
    assert (t["status"], t["prep_minutes"]) == ("collected", 15)
    hist = (
        await client.post(f"{API}/track/history", json={"tokens": [o["tracking_token"]]})
    ).json()[0]
    assert (hist["paid"], hist["status"]) == (o["till_amount"], "collected")
    report = (await client.get(f"{API}/hotel/reports", headers=w.owner)).json()["totals"]
    assert report["orders"] == 1 and report["mpesa"] == o["till_amount"]


async def test_delivery_two_riders_open_job_alarm_stops_for_everyone(client, db, w):
    await go_online(client, w.r1, w.r2)
    o = await place(client, w)
    await till_sms(client, w, new_code(), o["till_amount"])
    assert (await rider_alarms(client, w.r1))["open_jobs"] == 0  # not accepted yet: no job
    await hotel_step(client, w, o["code"], "accept", {"prep_minutes": 10})
    oid = await order_id(db, o["code"])
    assert (await rider_alarms(client, w.r1))["open_jobs"] == 1
    assert (await rider_alarms(client, w.r2))["open_jobs"] == 1  # both ring

    assert (await client.post(f"{API}/rider/jobs/{oid}/claim", headers=w.r2)).status_code == 200
    assert (await rider_alarms(client, w.r1))["open_jobs"] == 0  # someone took it: r1 stops too
    assert await rider_alarms(client, w.r2) == {"open_jobs": 0, "assigned_unseen": 0}
    r = await client.post(f"{API}/rider/jobs/{oid}/claim", headers=w.r1)
    assert r.json()["error"]["code"] == "job_taken"

    await hotel_step(client, w, o["code"], "preparing")
    await hotel_step(client, w, o["code"], "ready")
    card = await hotel_step(client, w, o["code"], "handed-to-rider")
    assert card["fee_handed"] is True and card["rider_name"]
    await client.post(
        f"{API}/rider/jobs/{oid}/picked-up", headers=w.r2, json={"fee_received": True}
    )
    await client.post(f"{API}/rider/jobs/{oid}/on-the-way", headers=w.r2)
    t = await track(client, o["tracking_token"])
    assert t["rider_name"] and t["status"] == "on_the_way"
    r = await client.post(
        f"{API}/rider/jobs/{oid}/delivered", headers=w.r2, json={"code": t["delivery_code"]}
    )
    assert r.json()["status"] == "delivered"
    fee = await db.scalar(
        select(LedgerEntry.amount).where(
            LedgerEntry.order_id == oid, LedgerEntry.entry_type == "rider_fee_instant"
        )
    )
    assert fee == o["till_amount"] - 670  # the rider fee in the Till
    assert (await db.get(Customer, "254712000111")).completed_orders == 1


async def test_admin_assignment_rings_rider_until_seen_and_swaps(client, db, w):
    o = await place(client, w)
    await till_sms(client, w, new_code(), o["till_amount"])
    await hotel_step(client, w, o["code"], "accept", {"prep_minutes": 10})
    oid = await order_id(db, o["code"])

    await client.post(
        f"{API}/admin/dispatch/{oid}/assign", headers=w.admin, json={"rider_id": str(w.r1_id)}
    )
    assert (await rider_alarms(client, w.r1))["assigned_unseen"] == 1  # rings even while offline
    board = (await client.get(f"{API}/admin/dispatch", headers=w.admin)).json()["orders"]
    assert next(x for x in board if x["id"] == str(oid))["rider_seen"] is False
    await client.post(f"{API}/rider/jobs/{oid}/seen", headers=w.r1)
    assert (await rider_alarms(client, w.r1))["assigned_unseen"] == 0  # "Got it": stops

    await client.post(
        f"{API}/admin/dispatch/{oid}/assign", headers=w.admin, json={"rider_id": str(w.r2_id)}
    )
    assert (await rider_alarms(client, w.r2))["assigned_unseen"] == 1
    assert [
        j for j in (await client.get(f"{API}/rider/jobs", headers=w.r1)).json() if j["mine"]
    ] == []
    # Acting on the job counts as seen: no separate tap needed.
    await hotel_step(client, w, o["code"], "preparing")
    await hotel_step(client, w, o["code"], "ready")
    await client.post(
        f"{API}/rider/jobs/{oid}/picked-up", headers=w.r2, json={"fee_received": True}
    )
    assert (await rider_alarms(client, w.r2))["assigned_unseen"] == 0


async def test_option_b_fee_not_paid_asks_customer_until_answered(client, db, w):
    o = await place(client, w, mode="cash")
    await till_sms(client, w, new_code(), o["till_amount"])
    await hotel_step(client, w, o["code"], "accept", {"prep_minutes": 10})
    oid = await order_id(db, o["code"])
    await go_online(client, w.r1)
    await client.post(f"{API}/rider/jobs/{oid}/claim", headers=w.r1)
    for step in ("preparing", "ready", "handed-to-rider"):
        await hotel_step(client, w, o["code"], step)
    t = await track(client, o["tracking_token"])
    await client.post(
        f"{API}/rider/jobs/{oid}/delivered",
        headers=w.r1,
        json={"code": t["delivery_code"], "cash_fee_received": False},
    )
    await client.post(f"{API}/rider/jobs/{oid}/fee-not-paid", headers=w.r1)
    assert (await track(client, o["tracking_token"]))[
        "fee_question"
    ] is True  # customer's page rings

    await client.post(f"{API}/track/{o['tracking_token']}/rider-fee-answer", json={"paid": False})
    assert (await track(client, o["tracking_token"]))["fee_question"] is False  # answered: stops
    comp = await db.scalar(
        select(LedgerEntry.amount).where(
            LedgerEntry.order_id == oid, LedgerEntry.entry_type == "rider_compensation"
        )
    )
    assert comp == 100
    # That number can no longer leave the rider fee as cash.
    q = (
        await client.post(
            f"{API}/quotes",
            json={
                k: v
                for k, v in order_body(w, mode="cash").items()
                if k in ("hotel_slug", "lines", "type", "rider_fee_mode", "phone", "lat", "lng")
            },
        )
    ).json()
    assert q["option_b_allowed"] is False
    r = await client.post(
        f"{API}/orders",
        headers={"Idempotency-Key": uuid.uuid4().hex},
        json={**order_body(w, mode="cash"), "expected_total": q["till_amount"]},
    )
    assert r.json()["error"]["code"] == "option_b_unavailable"


async def test_customer_cancels_paid_order_refund_rings_until_sent(client, db, w):
    o = await place(client, w, kind="pickup")
    await till_sms(client, w, new_code(), o["till_amount"])
    assert (await hotel_alarms(client, w))["new_orders"] == 1
    r = await client.post(f"{API}/track/{o['tracking_token']}/cancel")
    assert r.status_code == 200
    a = await hotel_alarms(client, w)
    assert a == {"new_orders": 0, "payments": 1}  # order alarm stops; refund to send rings
    refund = (await client.get(f"{API}/hotel/refunds", headers=w.cashier)).json()[0]
    assert refund["amount"] == o["till_amount"]
    await client.post(
        f"{API}/hotel/refunds/{refund['id']}/sent",
        headers=w.cashier,
        json={"mpesa_code": new_code()},
    )
    assert (await hotel_alarms(client, w))["payments"] == 0  # sent: stops


async def test_hotel_rejects_paid_order(client, db, w):
    o = await place(client, w)
    await till_sms(client, w, new_code(), o["till_amount"])
    await hotel_step(
        client, w, o["code"], "reject", {"reason": "sold_out", "note": "No pilau left"}
    )
    t = await track(client, o["tracking_token"])
    assert t["status"] == "rejected" and "No pilau left" in t["reason"]
    assert await hotel_alarms(client, w) == {"new_orders": 0, "payments": 1}  # refund to send


async def test_unaccepted_order_duty_alarm_then_auto_reject_and_pause(client, db, w):
    first = await place(client, w)
    await till_sms(client, w, new_code(), first["till_amount"])
    now = utcnow()
    assert (await admin_alarms(client, w, db, now + timedelta(minutes=4)))["unaccepted"] == 0
    assert (await admin_alarms(client, w, db, now + timedelta(minutes=6)))[
        "unaccepted"
    ] == 1  # duty rings
    second = await place(client, w, phone="0712000222")
    await till_sms(client, w, new_code(), second["till_amount"], phone="254712000222")

    assert await jobs.order_flow.auto_reject_late(db, now + timedelta(minutes=11)) == 2
    assert (await admin_alarms(client, w, db, now + timedelta(minutes=11)))[
        "unaccepted"
    ] == 0  # stops
    assert (await hotel_alarms(client, w)) == {
        "new_orders": 0,
        "payments": 2,
    }  # two refunds to send
    await db.refresh(w.hotel)
    assert w.hotel.accepting_orders is False  # two misses in a row
    body = order_body(w, phone="0712000333")
    q = (
        await client.post(
            f"{API}/quotes",
            json={
                k: body[k]
                for k in ("hotel_slug", "lines", "type", "rider_fee_mode", "phone", "lat", "lng")
            },
        )
    ).json()
    r = await client.post(
        f"{API}/orders",
        headers={"Idempotency-Key": uuid.uuid4().hex},
        json={**body, "expected_total": q["till_amount"]},
    )
    assert r.json()["error"]["code"] == "hotel_closed"


async def test_underpaid_and_overpaid_go_to_the_hotel_and_stop_when_resolved(client, db, w):
    short = await place(client, w, kind="pickup")
    over = await place(client, w, kind="pickup", phone="0712000222")
    # The customer who paid short typed their code; the one who paid extra didn't.
    short_code = new_code()
    await client.post(
        f"{API}/track/{short['tracking_token']}/payment-code", json={"code": short_code}
    )
    await till_sms(client, w, short_code, short["till_amount"] - 100)
    assert (await till_sms(client, w, new_code(), over["till_amount"] + 50, phone="254712000222"))[
        "result"
    ] == "unmatched"
    assert (await hotel_alarms(client, w))["payments"] == 2  # underpaid + unmatched payment

    for item in (await client.get(f"{API}/hotel/review-items", headers=w.owner)).json():
        if item["type"] == "underpaid":
            body = {"action": "accept_shortfall"}
        else:
            assert item["actions"] == ["match_order", "dismiss"]
            body = {"action": "match_order", "order_code": f"#{over['code']}"}
        r = await client.post(
            f"{API}/hotel/review-items/{item['id']}/resolve", headers=w.owner, json=body
        )
        assert r.status_code == 200, r.text
    # Matching the extra payment opens an "overpaid" item: refund the difference.
    items = (await client.get(f"{API}/hotel/review-items", headers=w.owner)).json()
    assert [i["type"] for i in items] == ["overpaid"]
    await client.post(
        f"{API}/hotel/review-items/{items[0]['id']}/resolve",
        headers=w.owner,
        json={"action": "refund_difference"},
    )
    a = await hotel_alarms(client, w)
    assert a == {"new_orders": 2, "payments": 1}  # both orders ring; the KES 50 refund to send
    refund = (await client.get(f"{API}/hotel/refunds", headers=w.cashier)).json()[0]
    assert refund["amount"] == 50


async def test_match_order_refuses_wrong_or_paid_orders(client, db, w):
    paid = await place(client, w, kind="pickup")
    await till_sms(client, w, new_code(), paid["till_amount"])
    await till_sms(client, w, new_code(), 999, phone="254712000999")
    item = (await client.get(f"{API}/hotel/review-items", headers=w.owner)).json()[0]
    url = f"{API}/hotel/review-items/{item['id']}/resolve"
    r = await client.post(
        url, headers=w.owner, json={"action": "match_order", "order_code": "NOPE12"}
    )
    assert r.json()["error"]["code"] == "order_not_found"
    r = await client.post(
        url, headers=w.owner, json={"action": "match_order", "order_code": paid["code"]}
    )
    assert r.json()["error"]["code"] == "already_paid"
    assert (await hotel_alarms(client, w))["payments"] == 1  # still waiting: keeps ringing


async def test_unpaid_order_expires_and_late_payment_is_reinstated(client, db, w):
    o = await place(client, w, kind="pickup")
    assert await jobs.expire_unpaid(db, utcnow() + timedelta(minutes=21)) == 1
    assert (await track(client, o["tracking_token"]))["status"] == "expired"
    # Paid late and didn't send the code: the hotel matches it to the expired order.
    assert (await till_sms(client, w, new_code(), o["till_amount"]))["result"] == "unmatched"
    item = (await client.get(f"{API}/hotel/review-items", headers=w.owner)).json()[0]
    await client.post(
        f"{API}/hotel/review-items/{item['id']}/resolve",
        headers=w.owner,
        json={"action": "match_order", "order_code": o["code"]},
    )
    items = (await client.get(f"{API}/hotel/review-items", headers=w.owner)).json()
    assert [i["type"] for i in items] == ["late_payment"]
    await client.post(
        f"{API}/hotel/review-items/{items[0]['id']}/resolve",
        headers=w.owner,
        json={"action": "reinstate"},
    )
    assert (await track(client, o["tracking_token"]))["status"] == "paid"
    assert await hotel_alarms(client, w) == {"new_orders": 1, "payments": 0}


async def test_cash_pickup_first_time_cap_and_collection(client, db, w):
    r = await client.post(
        f"{API}/orders",
        headers={"Idempotency-Key": uuid.uuid4().hex},
        json={**order_body(w, kind="pickup", pay="cash", qty=2), "expected_total": 1320},
    )
    assert r.json()["error"]["code"] == "cash_cap"  # first-time number, over KES 1,000
    o = await place(client, w, kind="pickup", pay="cash")
    assert (await hotel_alarms(client, w))["new_orders"] == 1  # cash orders ring straight away
    await hotel_step(client, w, o["code"], "accept", {"prep_minutes": 10})
    for step in ("preparing", "ready", "collected"):
        await hotel_step(client, w, o["code"], step)
    oid = await order_id(db, o["code"])
    cash = await db.scalar(
        select(LedgerEntry.amount).where(
            LedgerEntry.order_id == oid, LedgerEntry.entry_type == "cash_received"
        )
    )
    assert cash == o["till_amount"]


async def test_failed_deliveries_strike_suspend_and_release_jobs(client, db, w):
    await go_online(client, w.r1)

    async def delivery_on_road(phone):
        o = await place(client, w, phone=phone)
        await till_sms(client, w, new_code(), o["till_amount"], phone="254" + phone[1:])
        await hotel_step(client, w, o["code"], "accept", {"prep_minutes": 10})
        oid = await order_id(db, o["code"])
        await client.post(f"{API}/rider/jobs/{oid}/claim", headers=w.r1)
        return o, oid

    for n, phone in enumerate(("0712000401", "0712000402")):
        o, oid = await delivery_on_road(phone)
        for step in ("preparing", "ready", "handed-to-rider"):
            await hotel_step(client, w, o["code"], step)
        await client.post(
            f"{API}/rider/jobs/{oid}/failed", headers=w.r1, json={"reason": "accident"}
        )
        assert (await admin_alarms(client, w, db))["needs_decision"] == 1  # rings the admin
        item = next(
            i
            for i in (await client.get(f"{API}/admin/review-items", headers=w.admin)).json()
            if i["type"] == "failed_delivery"
        )
        if n == 1:
            waiting, waiting_id = await delivery_on_road("0712000403")  # r1 holds another job
        r = await client.post(
            f"{API}/admin/review-items/{item['id']}/resolve",
            headers=w.admin,
            json={"action": "rider_fault"},
        )
        assert r.status_code == 200, r.text
        assert (await admin_alarms(client, w, db))["needs_decision"] == 0  # decided: stops

    assert (await db.get(RiderProfile, w.r1_id)).kyc_status == "suspended"
    # The job r1 still held goes back to the pool and rings other riders.
    await db.refresh(await db.get(Order, waiting_id))
    assert (await db.get(Order, waiting_id)).rider_id is None
    await go_online(client, w.r2)
    assert (await rider_alarms(client, w.r2))["open_jobs"] == 1
    r = await client.post(f"{API}/rider/online", headers=w.r1, json={"online": True})
    assert r.status_code == 403


async def test_rider_cannot_go_offline_holding_a_job(client, db, w):
    await go_online(client, w.r1)
    o = await place(client, w)
    await till_sms(client, w, new_code(), o["till_amount"])
    await hotel_step(client, w, o["code"], "accept", {"prep_minutes": 10})
    oid = await order_id(db, o["code"])
    await client.post(f"{API}/rider/jobs/{oid}/claim", headers=w.r1)
    r = await client.post(f"{API}/rider/online", headers=w.r1, json={"online": False})
    assert r.json()["error"]["code"] == "has_jobs"
    await client.post(f"{API}/rider/jobs/{oid}/release", headers=w.r1)
    assert (
        await client.post(f"{API}/rider/online", headers=w.r1, json={"online": False})
    ).status_code == 200


async def test_admin_alarms_for_no_rider_and_long_delivery(client, db, w):
    o = await place(client, w)
    await till_sms(client, w, new_code(), o["till_amount"])
    for step, body in (("accept", {"prep_minutes": 10}), ("preparing", None), ("ready", None)):
        await hotel_step(client, w, o["code"], step, body)
    oid = await order_id(db, o["code"])
    later = utcnow() + timedelta(minutes=6)
    assert (await admin_alarms(client, w, db, later))["no_rider"] == 1  # ready, nobody took it
    await client.post(
        f"{API}/admin/dispatch/{oid}/assign", headers=w.admin, json={"rider_id": str(w.r1_id)}
    )
    assert (await admin_alarms(client, w, db, later))["no_rider"] == 0  # assigned: stops

    await hotel_step(client, w, o["code"], "handed-to-rider")
    much_later = utcnow() + timedelta(minutes=50)
    assert (await admin_alarms(client, w, db, much_later))[
        "long_delivery"
    ] == 1  # 50 min on the road
    t = await track(client, o["tracking_token"])
    await client.post(
        f"{API}/rider/jobs/{oid}/delivered", headers=w.r1, json={"code": t["delivery_code"]}
    )
    assert (await admin_alarms(client, w, db, much_later))["long_delivery"] == 0  # delivered: stops


async def test_double_taps_change_things_once(client, db, w):
    body = order_body(w, kind="pickup")
    q = (
        await client.post(
            f"{API}/quotes",
            json={
                k: body[k]
                for k in ("hotel_slug", "lines", "type", "rider_fee_mode", "phone", "lat", "lng")
            },
        )
    ).json()
    key = {"Idempotency-Key": uuid.uuid4().hex}
    a = await client.post(
        f"{API}/orders", headers=key, json={**body, "expected_total": q["till_amount"]}
    )
    b = await client.post(
        f"{API}/orders", headers=key, json={**body, "expected_total": q["till_amount"]}
    )
    assert a.json()["code"] == b.json()["code"]
    code = new_code()
    for _ in range(2):
        await till_sms(client, w, code, a.json()["till_amount"])
    oid = await order_id(db, a.json()["code"])
    paid = await db.scalar(
        select(LedgerEntry.amount).where(
            LedgerEntry.order_id == oid, LedgerEntry.entry_type == "till_received"
        )
    )
    assert paid == a.json()["till_amount"]  # once, not twice
    for _ in range(2):
        await hotel_step(client, w, a.json()["code"], "accept", {"prep_minutes": 10})


async def test_who_can_do_what(client, db, w):
    o = await place(client, w, kind="pickup")
    await till_sms(client, w, new_code(), o["till_amount"])
    oid = await order_id(db, o["code"])
    other_hotel, _ = await open_hotel(db)
    outsider = auth_header(await make_user(db, "hotel_admin", other_hotel))
    assert (
        await client.post(
            f"{API}/hotel/orders/{oid}/accept", headers=outsider, json={"prep_minutes": 5}
        )
    ).status_code == 404
    assert (await client.get(f"{API}/hotel/reports", headers=w.cashier)).status_code == 403
    assert (
        await client.put(
            f"{API}/hotel/settings", headers=w.cashier, json={"till_number": "5550000"}
        )
    ).status_code == 403
    assert (await client.get(f"{API}/admin/riders", headers=w.owner)).status_code == 403
    assert (await client.get(f"{API}/rider/jobs", headers=w.cashier)).status_code == 403
    assert (await client.get(f"{API}/hotel/orders", headers=w.r1)).status_code == 403
    assert (await client.get(f"{API}/track/not-a-real-token-123456")).status_code == 404


async def test_hotel_cancels_accepted_order_with_refund_and_rider_loses_job(client, db, w):
    await go_online(client, w.r1)
    o = await place(client, w)
    await till_sms(client, w, new_code(), o["till_amount"])
    await hotel_step(client, w, o["code"], "accept", {"prep_minutes": 15})
    await hotel_step(client, w, o["code"], "preparing")
    oid = await order_id(db, o["code"])
    await client.post(f"{API}/rider/jobs/{oid}/claim", headers=w.r1)

    body = {"reason": "ran_out", "note": "No more pilau"}
    r = await client.post(f"{API}/hotel/orders/{oid}/cancel", headers=w.cashier, json=body)
    assert r.status_code == 403  # a refund decision: hotel admin only
    r = await client.post(f"{API}/hotel/orders/{oid}/cancel", headers=w.owner, json=body)
    assert r.json()["status"] == "cancelled"
    assert (
        await client.post(f"{API}/hotel/orders/{oid}/cancel", headers=w.owner, json=body)
    ).status_code == 200  # repeat
    t = await track(client, o["tracking_token"])
    assert t["status"] == "cancelled" and "No more pilau" in t["reason"] and "hotel" in t["reason"]
    assert [
        j for j in (await client.get(f"{API}/rider/jobs", headers=w.r1)).json() if j["mine"]
    ] == []
    refunds = (await client.get(f"{API}/hotel/refunds", headers=w.cashier)).json()
    assert [r["amount"] for r in refunds] == [o["till_amount"]]
    assert (await hotel_alarms(client, w))["payments"] == 1  # refund to send rings


async def test_admin_finds_and_cancels_any_order_but_not_once_with_rider(client, db, w):
    o = await place(client, w)
    await till_sms(client, w, new_code(), o["till_amount"])
    await hotel_step(client, w, o["code"], "accept", {"prep_minutes": 15})
    found = (await client.get(f"{API}/admin/orders/%23{o['code'].lower()}", headers=w.admin)).json()
    assert (found["code"], found["can_cancel"]) == (o["code"], True)
    r = await client.post(
        f"{API}/admin/orders/{found['id']}/cancel",
        headers=w.admin,
        json={"reason": "customer_asked"},
    )
    assert r.json()["status"] == "cancelled"
    assert "Chakula" in (await track(client, o["tracking_token"]))["reason"]

    on_road = await place(client, w, phone="0712000555")
    await till_sms(client, w, new_code(), on_road["till_amount"], phone="254712000555")
    for step, b in (("accept", {"prep_minutes": 5}), ("preparing", None), ("ready", None)):
        await hotel_step(client, w, on_road["code"], step, b)
    oid = await order_id(db, on_road["code"])
    await client.post(
        f"{API}/admin/dispatch/{oid}/assign", headers=w.admin, json={"rider_id": str(w.r1_id)}
    )
    await hotel_step(client, w, on_road["code"], "handed-to-rider")
    r = await client.post(
        f"{API}/admin/orders/{oid}/cancel", headers=w.admin, json={"reason": "other"}
    )
    assert r.json()["error"]["code"] == "with_rider"
