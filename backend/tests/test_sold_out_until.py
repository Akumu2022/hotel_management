"""Items marked "back tomorrow" return to sale by themselves at the next opening."""

from datetime import UTC, datetime, time, timedelta

from app.models import HotelHours
from app.services import jobs
from tests.factories import auth_header, make_hotel, make_product, make_user


async def test_back_tomorrow_sets_a_time_and_the_job_restocks(client, db):
    hotel = await make_hotel(db)
    for day in range(7):
        db.add(HotelHours(hotel_id=hotel.id, weekday=day, opens_at=time(7), closes_at=time(22)))
    product = await make_product(db, hotel)
    cashier = auth_header(await make_user(db, "cashier", hotel))

    r = await client.patch(
        f"/api/v1/hotel/products/{product.id}",
        headers=cashier,
        json={"is_sold_out": True, "back_tomorrow": True},
    )
    assert r.status_code == 200, r.text
    until = datetime.fromisoformat(r.json()["sold_out_until"])
    assert r.json()["is_sold_out"] is True
    assert timedelta(0) < until - datetime.now(UTC) <= timedelta(days=2)
    assert (until + timedelta(hours=3)).time() == time(7)  # next opening, Kenya time

    # Not yet: nothing changes before that time. After it, the item is back on sale.
    assert await jobs.restock_products(db, until - timedelta(minutes=1)) == 0
    assert await jobs.restock_products(db, until + timedelta(minutes=1)) == 1
    await db.refresh(product)
    assert product.is_sold_out is False and product.sold_out_until is None


async def test_manual_switch_clears_back_tomorrow(client, db):
    hotel = await make_hotel(db)
    product = await make_product(db, hotel)
    admin = auth_header(await make_user(db, "hotel_admin", hotel))
    url = f"/api/v1/hotel/products/{product.id}"

    await client.patch(url, headers=admin, json={"is_sold_out": True, "back_tomorrow": True})
    r = await client.patch(url, headers=admin, json={"is_sold_out": True})
    assert r.json()["is_sold_out"] is True and r.json()["sold_out_until"] is None
    r = await client.patch(url, headers=admin, json={"is_sold_out": False})
    assert r.json()["is_sold_out"] is False and r.json()["sold_out_until"] is None
