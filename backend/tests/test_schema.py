"""Database-level guards: the CHECK constraints catch money that does not add up even if a
service has a bug."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.phone import normalize_phone
from app.models import OrderEvent
from tests.factories import make_hotel, make_order


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("till_amount", 769),  # till != food + service + rider-in-till
        ("food_net", 600),  # food_net != items_total - discount
        ("rider_fee_in_till", 0),  # option A must include the rider fee
        ("commission_amount", 10_000),  # more than the food
        ("service_fee", -1),
        ("status", "teleported"),
    ],
)
async def test_order_checks(db, column, value):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                text(f"UPDATE orders SET {column} = :v WHERE id = :id"),
                {"v": value, "id": order.id},
            )


async def test_cash_delivery_is_impossible(db):
    hotel = await make_hotel(db)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await make_order(db, hotel, payment_method="cash")


async def test_order_line_check(db):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel)
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO order_items (order_id, product_id, name_snapshot, unit_price,"
                    " options_price, quantity, line_discount, line_total)"
                    " SELECT :o, id, 'x', 100, 0, 2, 0, 150 FROM products LIMIT 1"
                ),
                {"o": order.id},
            )


async def test_order_events_are_append_only(db):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel)
    db.add(OrderEvent(order_id=order.id, to_status="awaiting_payment", actor_type="customer"))
    await db.flush()
    with pytest.raises(DBAPIError, match="append-only"):
        async with db.begin_nested():
            await db.execute(text("UPDATE order_events SET reason = 'x'"))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0712345678", "254712345678"),
        ("0112345678", "254112345678"),
        ("+254 712 345 678", "254712345678"),
        ("712345678", "254712345678"),
        ("254112345678", "254112345678"),
    ],
)
def test_phone_normalization(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["", "0812345678", "071234567", "25471234567890", "abc"])
def test_phone_rejects(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)
