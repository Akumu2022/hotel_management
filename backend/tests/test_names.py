"""D25: the payer's name on the Till SMS against the name typed at checkout."""

import pytest

from app.core.time import utcnow
from app.models import Order
from app.services import names, payments
from tests.factories import make_hotel, make_order


@pytest.mark.parametrize(
    ("checkout", "payer", "score"),
    [
        ("James Kamau", "KAMAU DANIEL JAMES", 2),  # any order
        ("James Kamau", "JAMES ONYANGO", 1),
        ("James Kamau", "Onyango James", 1),
        ("James Kamau", "PETER OTIENO", 0),
        ("Mohamed Ali Hassan", "MOHAMMED HASSAN", 2),  # one-letter slip
        ("Wanjiku Mwangi", "WANJKU MWANGI", 2),
        ("Kam", "KAMAU JOHN", 1),  # short form
        ("J. Kamau", "JOHN KAMAU", 1),  # an initial alone never counts
        ("Jo Ke", "JOHN KAMAU", None),  # nothing usable typed
        ("James Kamau", None, None),
        ("Amina", "Aminah Said", 1),
        ("Ann Wairimu", "ANNE WAIRIMU", 2),
        ("Éric Kipchoge", "ERIC KIPCHOGE", 2),  # accents
        ("Kamau Kamau", "KAMAU JAMES", 1),  # each payer name counts once
        ("Ken Otieno", "KEVIN OTIENO", 1),  # "Ken" is not "Kevin"
    ],
)
def test_match(checkout, payer, score):
    assert names.match(checkout, payer) == score


async def _waiting(db, hotel, name: str) -> Order:
    order = await make_order(db, hotel)
    order.customer_name = name
    await db.flush()
    return order


async def _sms(db, hotel, amount, payer, code, digits=None):
    """digits=None: the phone is fully masked, so only amount and name can match."""
    return await payments.record_incoming(
        db,
        till_number=hotel.till_number,
        code=code,
        amount=amount,
        paid_at=utcnow(),
        source="forwarder",
        phone_digits=digits,
        payer_name=payer,
        now=utcnow(),
    )


async def test_without_code_the_name_picks_the_order(db):
    """Two waiting orders with the same amount and phone digits: the name decides."""
    hotel = await make_hotel(db)
    james = await _waiting(db, hotel, "James Kamau")
    mary = await _waiting(db, hotel, "Mary Achieng")
    payment, outcome = await _sms(db, hotel, james.till_amount, "KAMAU DANIEL JAMES", "UJ2H08M4M1")
    assert outcome.result == "paid" and payment.order_id == james.id
    assert payment.name_match == 2 and payment.payer_name == "KAMAU DANIEL JAMES"
    await db.refresh(mary)
    assert mary.status == "awaiting_payment"


async def test_two_names_beat_one(db):
    hotel = await make_hotel(db)
    await _waiting(db, hotel, "James Onyango")
    exact = await _waiting(db, hotel, "James Kamau")
    payment, _ = await _sms(db, hotel, exact.till_amount, "JAMES KAMAU", "UJ2H08M4M2")
    assert payment.order_id == exact.id


async def test_wrong_name_without_code_goes_to_review(db):
    hotel = await make_hotel(db)
    order = await _waiting(db, hotel, "James Kamau")
    payment, outcome = await _sms(db, hotel, order.till_amount, "PETER OTIENO", "UJ2H08M4M3")
    assert outcome is None and payment.order_id is None
    await db.refresh(order)
    assert order.status == "awaiting_payment"
    items = await payments_reviews(db, hotel)
    assert any("doesn't" in r.reason and order.code in r.reason for r in items)


async def test_code_wins_over_a_different_name(db):
    """Someone else paid and the customer sent the code: paid, but the hotel sees the name."""
    hotel = await make_hotel(db)
    order = await _waiting(db, hotel, "James Kamau")
    await payments.submit_customer_code(db, order.id, "UJ2H08M4M4", utcnow())
    payment, outcome = await _sms(db, hotel, order.till_amount, "PETER OTIENO", "UJ2H08M4M4")
    assert outcome.result == "paid" and payment.name_match == 0


async def test_message_without_name_still_matches_by_amount_and_phone(db):
    hotel = await make_hotel(db)
    order = await _waiting(db, hotel, "James Kamau")
    payment, outcome = await _sms(db, hotel, order.till_amount, None, "UJ2H08M4M5")
    assert outcome.result == "paid" and payment.name_match is None


async def payments_reviews(db, hotel):
    from sqlalchemy import select

    from app.models import ReviewItem

    return (
        (await db.execute(select(ReviewItem).where(ReviewItem.hotel_id == hotel.id)))
        .scalars()
        .all()
    )


async def test_two_equal_orders_are_named_not_guessed(db):
    hotel = await make_hotel(db)
    a = await _waiting(db, hotel, "Achieng Atieno")
    b = await _waiting(db, hotel, "Achieng Atieno")
    payment, outcome = await _sms(db, hotel, a.till_amount, "ACHIENG ATIENO", "UJ2H08M4M6")
    assert outcome is None and payment.order_id is None
    [item] = await payments_reviews(db, hotel)
    assert "fits 2 orders" in item.reason and a.code in item.reason and b.code in item.reason


async def test_code_after_unmatched_sms_closes_the_unmatched_item(db):
    """SMS first (amount fits nothing), then the customer enters that code: the payment is
    linked, and the stale "which order?" item closes instead of offering a Match that fails."""
    hotel = await make_hotel(db)
    order = await _waiting(db, hotel, "James Kamau")
    await _sms(db, hotel, order.till_amount - 100, "KAMAU DANIEL JAMES", "UJ2H08M4M7")
    [item] = await payments_reviews(db, hotel)
    assert item.type == "unmatched_sms" and item.status == "open"
    out = await payments.submit_customer_code(db, order.id, "UJ2H08M4M7", utcnow())
    assert out.result == "underpaid"
    items = {i.type: i.status for i in await payments_reviews(db, hotel)}
    assert items == {"unmatched_sms": "resolved", "underpaid": "open"}
