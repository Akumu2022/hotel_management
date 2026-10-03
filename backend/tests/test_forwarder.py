"""M8: Till phone pairing, signed requests, SMS intake end to end (DECISIONS D26)."""

import json
import secrets
import time
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.core.time import utcnow
from app.models import ForwarderDevice, Payment, ReviewItem, SmsMessage
from app.services import forwarder, sms_parser
from tests.factories import auth_header, make_hotel, make_order, make_user

API = "/api/v1"


class Phone:
    """What the Android app does: pair once, then sign every request."""

    def __init__(self, client, device_id: str, secret: str):
        self.client, self.device_id, self.secret = client, device_id, bytes.fromhex(secret)

    async def post(
        self,
        path: str,
        payload: dict,
        *,
        ts: int | None = None,
        nonce: str | None = None,
        secret: bytes | None = None,
    ):
        body = json.dumps(payload).encode()
        ts = ts or int(time.time())
        nonce = nonce or secrets.token_hex(16)
        sig = forwarder.sign(secret or self.secret, str(ts), nonce, body)
        return await self.client.post(
            f"{API}{path}",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Device-Id": self.device_id,
                "X-Timestamp": str(ts),
                "X-Nonce": nonce,
                "X-Signature": sig,
            },
        )

    async def send(self, *texts: str, sender: str = "MPESA"):
        msgs = [
            {
                "id": f"msg-{secrets.token_hex(8)}",
                "sender": sender,
                "body": t,
                "received_at": int(time.time() * 1000),
            }
            for t in texts
        ]
        return await self.post("/forwarder/sms", {"messages": msgs}), msgs


def masked(order) -> str:
    """The payer's number as the Till SMS shows it, for this order's customer."""
    return order.customer_phone[:4] + "******" + order.customer_phone[-3:]


def till_sms(
    code: str, amount: int, name: str = "JAMES KAMAU", phone: str = "2547******123", when=None
) -> str:
    """A Till SMS in the real format (docs/sms_samples), dated now in Kenya time."""
    t = (when or utcnow()) + timedelta(hours=3)
    h = t.hour % 12 or 12
    ampm = "AM" if t.hour < 12 else "PM"
    return (
        f"{code} Confirmed.on {t.day}/{t.month}/{t.year % 100} at {h}:{t.minute:02d} {ampm}"
        f"KSH{amount:,}.00 received from {phone} {name}. New Account balance is KSH1,090.05. "
        "Transaction cost, KSH0.00."
    )


async def paired(client, db):
    hotel = await make_hotel(db)
    owner = await make_user(db, "hotel_admin", hotel)
    r = await client.post(f"{API}/hotel/forwarder/pairing", headers=auth_header(owner))
    assert r.status_code == 201
    code = r.json()["code"]
    assert len(code) == 9 and code[4] == "-"
    r = await client.post(
        f"{API}/forwarder/pair",
        json={"code": code.lower(), "label": "Tecno Spark", "app_version": "1.0"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["till_number"] == hotel.till_number and body["hotel_name"] == hotel.name
    return hotel, owner, Phone(client, body["device_id"], body["secret"]), code


def test_sample_sms_still_parses():
    """The helper makes the same format as the real samples."""
    p = sms_parser.parse(till_sms("UJ2H08M4M3", 1520, "KAMAU DANIEL JAMES"))
    assert (p.status, p.amount, p.sender_name) == ("parsed", 1520, "KAMAU DANIEL JAMES")


async def test_pair_and_payment_confirms_order(client, db):
    hotel, owner, phone, code = await paired(client, db)
    order = await make_order(db, hotel)
    order.customer_name = "James Kamau"
    await db.flush()

    r, msgs = await phone.send(
        till_sms("UJ3AB12CD4", order.till_amount, "KAMAU DANIEL JAMES", masked(order))
    )
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == [msgs[0]["id"]]
    await db.refresh(order)
    assert order.status == "paid"
    pay = await db.scalar(select(Payment).where(Payment.order_id == order.id))
    assert (pay.source, pay.payer_name, pay.name_match) == ("forwarder", "KAMAU DANIEL JAMES", 2)

    # The pairing code works once only.
    again = await client.post(f"{API}/forwarder/pair", json={"code": code})
    assert again.status_code == 400

    # The hotel sees its phone as online.
    status = (await client.get(f"{API}/hotel/forwarder", headers=auth_header(owner))).json()
    [dev] = status["devices"]
    assert dev["online"] and dev["label"] == "Tecno Spark" and dev["last_sms_at"]


async def test_resending_is_harmless(client, db):
    hotel, _, phone, _ = await paired(client, db)
    order = await make_order(db, hotel)
    text = till_sms("UJ3AB12CD5", order.till_amount, "JAMES KAMAU", masked(order))
    r, msgs = await phone.send(text)
    # The same message again (retry after a lost reply), and again from the inbox rescan.
    r2 = await phone.post("/forwarder/sms", {"messages": msgs})
    assert r2.json()["accepted"] == [msgs[0]["id"]]
    r3, _ = await phone.send(text)
    assert r3.status_code == 200
    n = await db.scalar(
        select(func.count()).select_from(Payment).where(Payment.trans_code == "UJ3AB12CD5")
    )
    assert n == 1


async def test_non_mpesa_messages_are_dropped(client, db):
    _, _, phone, _ = await paired(client, db)
    r, msgs = await phone.send("Your OTP is 1234", sender="Safaricom")
    assert r.json()["accepted"] == [msgs[0]["id"]]  # acknowledged so the phone forgets it
    stored = await db.scalar(
        select(func.count())
        .select_from(SmsMessage)
        .where(SmsMessage.raw_text == "Your OTP is 1234")
    )
    assert stored == 0


async def test_unreadable_sms_goes_to_review(client, db):
    hotel, _, phone, _ = await paired(client, db)
    r, _ = await phone.send("Confirmed. Something M-Pesa changed in the format")
    assert r.status_code == 200
    items = (
        (await db.execute(select(ReviewItem).where(ReviewItem.hotel_id == hotel.id)))
        .scalars()
        .all()
    )
    assert [i.type for i in items] == ["parse_failed"]


async def test_bad_signatures_are_refused(client, db):
    _, _, phone, _ = await paired(client, db)
    hb = {"battery": 80}
    assert (await phone.post("/forwarder/heartbeat", hb, secret=b"x" * 32)).status_code == 401
    old = int(time.time()) - 600
    r = await phone.post("/forwarder/heartbeat", hb, ts=old)
    assert r.status_code == 401 and r.json()["error"]["code"] == "clock_skew"
    nonce = secrets.token_hex(16)
    assert (await phone.post("/forwarder/heartbeat", hb, nonce=nonce)).status_code == 200
    replay = await phone.post("/forwarder/heartbeat", hb, nonce=nonce)
    assert replay.status_code == 401 and replay.json()["error"]["code"] == "replayed"
    # A tampered body fails: sign one body, send another.
    body = json.dumps({"battery": 5}).encode()
    ts, n = str(int(time.time())), secrets.token_hex(16)
    sig = forwarder.sign(phone.secret, ts, n, json.dumps({"battery": 99}).encode())
    r = await client.post(
        f"{API}/forwarder/heartbeat",
        content=body,
        headers={
            "X-Device-Id": phone.device_id,
            "X-Timestamp": ts,
            "X-Nonce": n,
            "X-Signature": sig,
        },
    )
    assert r.status_code == 401


async def test_new_phone_replaces_old_and_unpair(client, db):
    hotel, owner, old_phone, _ = await paired(client, db)
    code = (await client.post(f"{API}/hotel/forwarder/pairing", headers=auth_header(owner))).json()[
        "code"
    ]
    body = (await client.post(f"{API}/forwarder/pair", json={"code": code})).json()
    new_phone = Phone(client, body["device_id"], body["secret"])
    r = await old_phone.post("/forwarder/heartbeat", {})
    assert r.status_code == 401 and r.json()["error"]["code"] == "unpaired"
    assert (await new_phone.post("/forwarder/heartbeat", {"battery": 50})).status_code == 200

    # Another hotel can't unpair it; its own admin can.
    other_admin = await make_user(db, "hotel_admin", await make_hotel(db))
    assert (
        await client.delete(
            f"{API}/hotel/forwarder/{new_phone.device_id}", headers=auth_header(other_admin)
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"{API}/hotel/forwarder/{new_phone.device_id}", headers=auth_header(owner)
        )
    ).status_code == 204
    assert (await new_phone.post("/forwarder/heartbeat", {})).status_code == 401


async def test_offline_and_permission_problems_show(client, db):
    hotel, owner, phone, _ = await paired(client, db)
    await phone.post("/forwarder/heartbeat", {"battery": 15, "pending": 3, "sms_permission": False})
    [dev] = (await client.get(f"{API}/hotel/forwarder", headers=auth_header(owner))).json()[
        "devices"
    ]
    assert dev["problems"] == ["no_sms_permission"] and dev["battery"] == 15

    d = await db.get(ForwarderDevice, uuid.UUID(phone.device_id))
    d.last_heartbeat_at = utcnow() - timedelta(hours=1)
    await db.flush()
    out = forwarder.device_out(d, utcnow())
    assert (
        not out["online"] and "offline" in out["problems"] and "messages_waiting" in out["problems"]
    )

    admin = await make_user(db, "super_admin")
    body = (await client.get(f"{API}/admin/forwarder", headers=auth_header(admin))).json()
    assert any(x["id"] == phone.device_id for x in body["devices"])


async def test_cashier_cannot_pair(client, db):
    hotel = await make_hotel(db)
    cashier = await make_user(db, "cashier", hotel)
    assert (
        await client.post(f"{API}/hotel/forwarder/pairing", headers=auth_header(cashier))
    ).status_code == 403


async def test_one_bad_message_does_not_block_the_rest(client, db, monkeypatch):
    hotel, _, phone, _ = await paired(client, db)
    order = await make_order(db, hotel)
    real = forwarder._one

    async def flaky(session, device, m, now):
        if "BOOM" in m.body:
            raise RuntimeError("bug")
        return await real(session, device, m, now)

    monkeypatch.setattr(forwarder, "_one", flaky)
    r, msgs = await phone.send(
        "BOOM", till_sms("UJ3AB12CD6", order.till_amount, "TEST CUSTOMER", masked(order))
    )
    assert r.status_code == 200 and len(r.json()["accepted"]) == 2
    await db.refresh(order)
    assert order.status == "paid"


async def test_expired_pairing_code(client, db):
    hotel = await make_hotel(db)
    code, _ = await forwarder.create_pairing(db, hotel.id, None, utcnow() - timedelta(minutes=20))
    await db.flush()
    r = await client.post(f"{API}/forwarder/pair", json={"code": code})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_pairing_code"


async def test_prune_nonces(client, db):
    _, _, phone, _ = await paired(client, db)
    await phone.post("/forwarder/heartbeat", {})
    assert await forwarder.prune_nonces(db, utcnow() + timedelta(hours=2)) >= 1
