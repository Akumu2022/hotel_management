"""Till SMS simulation: the real 2 Oct 2026 message format, run through the paired phone's API.

The message below is the owner's real Till SMS byte for byte except the payer's name and number,
which are replaced (same length and shape: full 12-digit number, three names). It proves the
order is confirmed with no typing at the hotel, and shows what still needs a human.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Customer, Payment, ReviewItem
from app.services import sms_parser
from tests.factories import make_order
from tests.test_forwarder import paired, till_sms

REAL = (
    "UJ2A293WLS Confirmed.on 2/10/26 at 8:39 PMKSH410.00 received from 254711222333 "
    "Stephen Otieno Mwangi. New Account balance is KSH2,240.05. Transaction cost, KSH0.00. "
    "Receiving payments of Ksh 500 & below in your Lipa na M-PESA till is now FREE!14:32"
)
PAID_AT = datetime(2026, 10, 2, 17, 39, tzinfo=UTC)  # 8:39 PM Kenya time


async def _order(db, hotel, *, name="Stephen Mwangi", phone="254711222333", minutes_before=4):
    order = await make_order(db, hotel, food=390, order_type="pickup", rider_fee_mode="none")
    await db.merge(Customer(phone=phone, name=name))
    await db.flush()
    order.customer_name, order.customer_phone = name, phone
    order.created_at = PAID_AT - timedelta(minutes=minutes_before)
    order.expires_at = order.created_at + timedelta(minutes=20)
    await db.flush()
    assert order.till_amount == 410
    return order


async def _reviews(db, hotel):
    return (
        (await db.execute(select(ReviewItem).where(ReviewItem.hotel_id == hotel.id)))
        .scalars()
        .all()
    )


def test_real_message_parses():
    p = sms_parser.parse(REAL)
    assert (p.status, p.code, p.amount, p.phone_digits, p.sender_name) == (
        "parsed",
        "UJ2A293WLS",
        410,
        "254711222333",
        "Stephen Otieno Mwangi",
    )
    assert p.paid_at == PAID_AT


async def test_customer_types_nothing_order_confirms_itself(client, db):
    hotel, _, phone, _ = await paired(client, db)
    order = await _order(db, hotel)
    r, _ = await phone.send(REAL)
    assert r.status_code == 200, r.text
    await db.refresh(order)
    assert order.status == "paid"
    pay = await db.scalar(select(Payment).where(Payment.trans_code == "UJ2A293WLS"))
    assert (pay.order_id, pay.source, pay.status) == (order.id, "forwarder", "matched")
    assert await _reviews(db, hotel) == []


async def test_customer_typed_code_first(client, db):
    hotel, _, phone, _ = await paired(client, db)
    order = await _order(db, hotel, name="Mary Wanjiku")  # someone else paid for her
    order.customer_trans_code = "UJ2A293WLS"
    await db.flush()
    await phone.send(REAL)
    await db.refresh(order)
    assert order.status == "paid"  # the code decides, the name doesn't matter


async def test_sms_first_then_customer_code(client, db):
    hotel, _, phone, _ = await paired(client, db)
    order = await _order(db, hotel, name="Mary Wanjiku", phone="254700000999")
    await phone.send(REAL)
    await db.refresh(order)
    assert order.status == "awaiting_payment"  # different person, different number: not guessed
    r = await client.post(
        f"/api/v1/track/{order.tracking_token}/payment-code", json={"code": "UJ2A293WLS"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "paid"
    await db.refresh(order)
    assert order.status == "paid"


async def test_two_same_orders_go_to_review(client, db):
    hotel, _, phone, _ = await paired(client, db)
    a = await _order(db, hotel, minutes_before=6)
    b = await _order(db, hotel, minutes_before=3)
    await phone.send(REAL)
    await db.refresh(a)
    await db.refresh(b)
    assert (a.status, b.status) == ("awaiting_payment", "awaiting_payment")
    [item] = await _reviews(db, hotel)
    assert item.type == "unmatched_sms" and "2 orders equally" in item.reason


async def test_underpaid_goes_to_review(client, db):
    hotel, _, phone, _ = await paired(client, db)
    order = await _order(db, hotel)
    order.customer_trans_code = "UJ2A293WLS"
    await db.flush()
    await phone.send(REAL.replace("KSH410.00", "KSH400.00"))
    await db.refresh(order)
    assert order.status == "checking_payment"
    assert [i.type for i in await _reviews(db, hotel)] == ["underpaid"]


async def test_same_sms_twice_counts_once(client, db):
    hotel, _, phone, _ = await paired(client, db)
    order = await _order(db, hotel)
    await phone.send(REAL)
    await phone.send(REAL)
    await db.refresh(order)
    assert order.status == "paid"
    assert len((await db.execute(select(Payment).where(Payment.order_id == order.id))).all()) == 1


async def test_old_code_reused_on_new_order(client, db):
    hotel, _, phone, _ = await paired(client, db)
    order = await _order(db, hotel, minutes_before=-30)  # order made 30 min AFTER the payment
    order.customer_trans_code = "UJ2A293WLS"
    await db.flush()
    await phone.send(REAL)
    await db.refresh(order)
    assert order.status == "awaiting_payment"
    assert "older than the order" in (await _reviews(db, hotel))[0].reason


async def test_helper_matches_real_format():
    """The test helper and the real message parse the same way."""
    a = sms_parser.parse(REAL)
    b = sms_parser.parse(
        till_sms("UJ2A293WLS", 410, "Stephen Otieno Mwangi", "254711222333", when=PAID_AT)
    )
    assert (a.code, a.amount, a.paid_at, a.phone_digits) == (
        b.code,
        b.amount,
        b.paid_at,
        b.phone_digits,
    )


async def test_full_number_beats_a_different_name(client, db):
    """D28: the SMS shows the whole number; the checkout name was a nickname."""
    hotel, _, phone, _ = await paired(client, db)
    order = await _order(db, hotel, name="Steve")
    await phone.send(REAL)
    await db.refresh(order)
    assert order.status == "paid"


async def test_full_number_of_someone_else_is_not_guessed(client, db):
    hotel, _, phone, _ = await paired(client, db)
    order = await _order(db, hotel, phone="254700000999")  # same name, other number
    await phone.send(REAL)
    await db.refresh(order)
    assert order.status == "awaiting_payment"
