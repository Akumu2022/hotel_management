"""Web Push: who gets woken for what, and that dead subscriptions clean themselves up."""

import uuid
from types import SimpleNamespace

import pytest
from pywebpush import WebPushException
from sqlalchemy import select

from app.core.config import Config
from app.models import PushSubscription
from app.services import delivery, events, payments, push
from tests.factories import auth_header, make_hotel, make_user
from tests.test_delivery import API, make_rider, ready_delivery

ENDPOINT = "https://push.example.com/send/abc123"
KEYS = {"p256dh": "B" * 40, "auth": "a" * 20}


@pytest.fixture
def push_on(monkeypatch):
    monkeypatch.setattr(
        push, "get_config", lambda: Config(vapid_private_key="x" * 40, vapid_public_key="y" * 40)
    )


@pytest.fixture
def queued(monkeypatch, push_on):
    """Every Web Push message queued during a test, as (audience, title, tag)."""
    sent = []
    real = events.emit

    def spy(session, channel, payload):
        if channel == push.CHANNEL:
            sent.append((payload["audience"], payload["title"], payload["tag"]))
        return real(session, channel, payload)

    monkeypatch.setattr(events, "emit", spy)
    return sent


async def test_config_and_subscriptions(client, db):
    assert (await client.get(f"{API}/push/config")).json() == {"enabled": False, "public_key": None}
    body = {"endpoint": ENDPOINT, "keys": KEYS}
    assert (await client.post(f"{API}/push/subscribe", json=body)).status_code == 401

    cashier = await make_user(db, "cashier", await make_hotel(db))
    other = await make_user(db, "super_admin")
    mine, theirs = auth_header(cashier), auth_header(other)
    assert (await client.post(f"{API}/push/subscribe", headers=mine, json=body)).status_code == 204
    # The same browser again changes nothing; a plain-http endpoint is refused.
    assert (await client.post(f"{API}/push/subscribe", headers=mine, json=body)).status_code == 204
    bad = {"endpoint": "http://insecure.example.com/x", "keys": KEYS}
    assert (await client.post(f"{API}/push/subscribe", headers=mine, json=bad)).status_code == 422
    subs = (await db.execute(select(PushSubscription))).scalars().all()
    assert [s.user_id for s in subs] == [cashier.id]

    # Someone else signing in on that browser takes it over; only the owner can remove it.
    assert (
        await client.post(f"{API}/push/subscribe", headers=theirs, json=body)
    ).status_code == 204
    unsub = f"{API}/push/unsubscribe"
    gone = {"endpoint": ENDPOINT}
    assert (await client.post(unsub, headers=mine, json=gone)).status_code == 204
    assert await db.scalar(select(PushSubscription.id)) is not None  # not theirs: still there
    assert (await client.post(unsub, headers=theirs, json=gone)).status_code == 204
    assert await db.scalar(select(PushSubscription.id)) is None


async def test_nothing_is_queued_when_push_is_off(db, monkeypatch):
    seen = []
    monkeypatch.setattr(events, "emit", lambda s, ch, p: seen.append(ch))
    push.notify(db, title="x", body="y", url="/", tag="t", admins=True)
    assert seen == []


def fake_order(**kw):
    base = {
        "id": uuid.uuid4(),
        "code": "ABC123",
        "status": "paid",
        "payment_method": "mpesa",
        "type": "delivery",
        "hotel_id": uuid.uuid4(),
        "rider_id": None,
        "tracking_token": "tok",
    }
    return SimpleNamespace(**{**base, **kw})


def test_new_order_wakes_the_hotel_and_a_ready_delivery_wakes_online_riders(queued):
    session = SimpleNamespace(info={})
    order = fake_order(status="paid")
    events._push_for(session, order)
    assert [(a["hotel_id"], t, tag) for a, t, tag in queued] == [
        (str(order.hotel_id), "New order #ABC123", "hotel-orders")
    ]
    queued.clear()
    events._push_for(session, fake_order(status="awaiting_payment", payment_method="cash"))
    assert [tag for _, _, tag in queued] == ["hotel-orders"]  # cash is accepted before paying
    queued.clear()
    events._push_for(session, fake_order(status="awaiting_payment"))  # not paid yet: no alarm
    events._push_for(session, fake_order(status="preparing"))
    assert queued == []
    events._push_for(session, fake_order(status="ready"))
    assert [(a["online_riders"], tag) for a, _, tag in queued] == [(True, "rider-open")]
    queued.clear()
    events._push_for(session, fake_order(status="ready", rider_id=uuid.uuid4()))  # already taken
    assert queued == []


async def test_assignment_and_review_items_wake_the_right_people(db, queued):
    hotel = await make_hotel(db)
    order = await ready_delivery(db, hotel)
    rider = await make_rider(db)
    admin = await make_user(db, "super_admin")
    queued.clear()
    await delivery.assign(db, order.id, rider.id, admin.id, order.created_at)
    assert [(a["rider_id"], tag) for a, _, tag in queued] == [(str(rider.id), "rider-assigned")]

    queued.clear()
    await payments.open_review(
        db, type="failed_delivery", hotel_id=hotel.id, reason="Rider said no"
    )
    await payments.open_review(db, type="late_payment", hotel_id=hotel.id, reason="Code seen late")
    await payments.open_review(db, type="unmatched_sms", hotel_id=None, reason="Unknown Till")
    assert [(a["admins"], a["hotel_id"] is not None, tag) for a, _, tag in queued] == [
        (True, False, "admin-review"),
        (False, True, "hotel-payments"),
        (True, False, "admin-review"),
    ]


async def test_deliver_reaches_the_audience_and_drops_dead_subscriptions(
    committed, push_on, monkeypatch
):
    async with committed() as s:
        hotel = await make_hotel(s)
        cashier = await make_user(s, "cashier", hotel)
        elsewhere = await make_user(s, "cashier", await make_hotel(s))
        s.add_all(
            [
                PushSubscription(user_id=cashier.id, endpoint=ENDPOINT + "/ok", keys=KEYS),
                PushSubscription(user_id=cashier.id, endpoint=ENDPOINT + "/gone", keys=KEYS),
                PushSubscription(user_id=elsewhere.id, endpoint=ENDPOINT + "/other", keys=KEYS),
            ]
        )
        await s.commit()
        hotel_id = hotel.id

    delivered = []

    def fake_send(endpoint, keys, data):
        if endpoint.endswith("/gone"):
            raise WebPushException("gone", response=SimpleNamespace(status_code=410))
        delivered.append(endpoint)

    monkeypatch.setattr(push, "SessionLocal", committed)
    monkeypatch.setattr(push, "_send", fake_send)
    audience = {"hotel_id": str(hotel_id), "admins": False, "rider_id": None}
    payload = {
        "title": "New order",
        "body": "Accept it",
        "url": "/hotel/orders",
        "tag": "hotel-orders",
        "audience": {**audience, "online_riders": False},
    }
    assert await push.deliver(payload) == 1
    assert delivered == [ENDPOINT + "/ok"]  # the other hotel's phone is left alone
    async with committed() as s:
        left = (await s.execute(select(PushSubscription.endpoint))).scalars().all()
    assert sorted(left) == [ENDPOINT + "/ok", ENDPOINT + "/other"]  # the dead one is gone
