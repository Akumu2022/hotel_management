from app.models import Product
from tests.factories import make_category, make_hotel


async def test_typical_prep_time_is_the_median(client, db):
    hotel = await make_hotel(db, slug="eta-hotel")
    cat = await make_category(db, hotel)
    for minutes in (10, 20, 45):
        db.add(
            Product(
                hotel_id=hotel.id,
                category_id=cat.id,
                name=f"D{minutes}",
                price=100,
                prep_minutes=minutes,
            )
        )
    db.add(
        Product(
            hotel_id=hotel.id,
            category_id=cat.id,
            name="Old",
            price=100,
            prep_minutes=90,
            is_archived=True,
        )
    )
    await db.flush()
    hotels = {h["slug"]: h for h in (await client.get("/api/v1/hotels")).json()}
    assert hotels["eta-hotel"]["prep_minutes"] == 20
    menu = (await client.get("/api/v1/hotels/eta-hotel/menu")).json()
    assert menu["hotel"]["prep_minutes"] == 20


async def test_hotel_without_dishes_defaults_to_15(client, db):
    await make_hotel(db, slug="empty-hotel")
    hotels = {h["slug"]: h for h in (await client.get("/api/v1/hotels")).json()}
    assert hotels["empty-hotel"]["prep_minutes"] == 15
