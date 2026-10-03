"""Demo data for local testing: 3 hotels with Kenyan menus, hours, a discount, a promo code and
an offer. Safe to run twice (existing slugs are skipped). Never run against production."""

from datetime import time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.core.time import utcnow
from app.models import (
    Category,
    Discount,
    Hotel,
    HotelHours,
    Offer,
    Product,
    ProductOption,
    User,
)

EXTRAS = [("Extras", "Kachumbari", 30), ("Extras", "Extra chapati", 50)]
SIZE = [("Size", "Large", 100)]

# slug, name, phone, till, accent, staff phone, menu {category: [(name, price, desc, options)]}
HOTELS = [
    (
        "noor-cafe",
        "Noor Cafe",
        "0711000101",
        "5550101",
        "#b45309",
        "0722000101",
        {
            "Breakfast": [
                ("Chai", 60, "Kenyan tea with milk", []),
                ("Mandazi (3 pcs)", 60, "Fresh, lightly sweet", []),
                ("Eggs & sausage", 250, "Two eggs your way, beef sausage", []),
            ],
            "Mains": [
                ("Fish & ugali", 650, "Whole fried tilapia, ugali, sukuma", EXTRAS),
                ("Beef stew & chapati", 450, "Slow-cooked beef, two chapatis", EXTRAS),
                ("Pilau", 650, "Spiced rice with beef", EXTRAS + SIZE),
            ],
            "Drinks": [
                ("Fresh passion juice", 150, "", []),
                ("Soda 500 ml", 100, "", []),
            ],
        },
    ),
    (
        "jadelica",
        "Jadelica",
        "0711000202",
        "5550202",
        "#15803d",
        "0722000202",
        {
            "Grill": [
                (
                    "Nyama choma ½ kg",
                    900,
                    "Goat, with kachumbari",
                    [("Side", "Ugali", 50), ("Side", "Chips", 100)],
                ),
                ("Chicken quarter", 450, "Grilled, with chips", []),
                ("Mutura", 200, "", []),
            ],
            "Sides": [
                ("Chips masala", 300, "Spicy tomato chips", SIZE),
                ("Kachumbari", 80, "", []),
            ],
            "Drinks": [("Soda 500 ml", 100, "", []), ("Water 1 L", 80, "", [])],
        },
    ),
    (
        "sawan",
        "Sawan",
        "0711000303",
        "5550303",
        "#1d4ed8",
        "0722000303",
        {
            "Vegetarian": [
                (
                    "Githeri",
                    250,
                    "Maize and beans, fried with onion and tomato",
                    [("Extras", "Avocado", 50)],
                ),
                ("Chapati & beans", 220, "", []),
                ("Mukimo", 300, "Mashed potatoes, peas, maize and greens", []),
            ],
            "Drinks": [("Chai", 50, "", []), ("Fresh mango juice", 150, "", [])],
        },
    ),
    (
        "the-hood",
        "The Hood",
        "0711000404",
        "5551234",
        "#7c3aed",
        "0722222222",
        {
            "Burgers & wraps": [
                (
                    "Beef burger",
                    550,
                    "Grilled patty, cheese, chips",
                    [("Extras", "Extra cheese", 50)],
                ),
                ("Chicken wrap", 450, "Grilled chicken, salad, garlic sauce", []),
            ],
            "Sides": [("Chips", 200, "", SIZE), ("Smokie pasua", 70, "With kachumbari", [])],
            "Drinks": [
                ("Milkshake", 300, "Vanilla, chocolate or strawberry", []),
                ("Soda 500 ml", 100, "", []),
            ],
        },
    ),
    (
        "siri-tamu",
        "Siri-Tamu",
        "0711000505",
        "5550505",
        "#db2777",
        "0722000505",
        {
            "Swahili dishes": [
                ("Biryani", 600, "Coastal-style spiced rice with chicken", SIZE),
                ("Pilau & kachumbari", 450, "", []),
                ("Samosa (3 pcs)", 150, "Beef samosas", []),
            ],
            "Sweet": [("Mahamri & chai", 120, "", []), ("Kaimati (6 pcs)", 100, "", [])],
            "Drinks": [("Tangawizi tea", 70, "Ginger tea", []), ("Fresh lemonade", 150, "", [])],
        },
    ),
    (
        "tuutis",
        "Tuutis",
        "0711000606",
        "5550606",
        "#0f766e",
        "0722000606",
        {
            "Breakfast": [
                ("Full breakfast", 450, "Eggs, sausage, toast, beans, tea", []),
                ("Chapati & tea", 100, "", []),
            ],
            "Lunch": [
                ("Chicken & rice", 500, "Stewed chicken, rice, cabbage", EXTRAS),
                ("Ugali, sukuma & beef", 400, "", EXTRAS),
            ],
            "Drinks": [("Fresh passion juice", 150, "", []), ("Water 500 ml", 50, "", [])],
        },
    ),
]

# Bungoma CBD pick-up points (DECISIONS D14/D16): delivery fees are measured from here.
LOCATIONS = {
    "noor-cafe": (0.5652, 34.5588),
    "jadelica": (0.5610, 34.5645),
    "sawan": (0.5683, 34.5562),
    "the-hood": (0.5756, 34.5789),
    "siri-tamu": (0.5641, 34.5611),
    "tuutis": (0.5668, 34.5627),
}

STAFF_PASSWORD = "hotel-pass-123"


async def seed(session: AsyncSession) -> list[str]:
    now = utcnow()
    created = []
    for slug, name, phone, till, accent, staff_phone, menu in HOTELS:
        exists = await session.scalar(select(Hotel.id).where(Hotel.slug == slug))
        if exists:
            continue
        hotel = Hotel(
            name=name,
            slug=slug,
            phone="254" + phone[1:],
            till_number=till,
            accent_color=accent,
            lat=LOCATIONS[slug][0],
            lng=LOCATIONS[slug][1],
        )
        session.add(hotel)
        await session.flush()
        session.add_all(
            HotelHours(hotel_id=hotel.id, weekday=d, opens_at=time(6), closes_at=time(23, 30))
            for d in range(7)
        )
        session.add(
            User(
                role="hotel_admin",
                hotel_id=hotel.id,
                name=f"{name} Admin",
                phone="254" + staff_phone[1:],
                password_hash=hash_password(STAFF_PASSWORD),
            )
        )
        first_product = None
        for sort, (cat_name, dishes) in enumerate(menu.items()):
            cat = Category(hotel_id=hotel.id, name=cat_name, sort_order=sort)
            session.add(cat)
            await session.flush()
            for dish, price, desc, options in dishes:
                p = Product(
                    hotel_id=hotel.id, category_id=cat.id, name=dish, price=price, description=desc
                )
                session.add(p)
                await session.flush()
                first_product = first_product or p
                session.add_all(
                    ProductOption(
                        product_id=p.id, group_name=g, name=n, price_delta=d, sort_order=i
                    )
                    for i, (g, n, d) in enumerate(options)
                )
        if slug == "noor-cafe":
            # 10 % off pilau automatically; KARIBU = KES 50 off orders over 500.
            pilau = await session.scalar(
                select(Product).where(Product.hotel_id == hotel.id, Product.name == "Pilau")
            )
            session.add_all(
                [
                    Discount(
                        hotel_id=hotel.id,
                        scope="item",
                        product_id=pilau.id,
                        kind="percent",
                        value=1000,
                        starts_at=now - timedelta(days=1),
                    ),
                    Discount(
                        hotel_id=hotel.id,
                        scope="order",
                        kind="fixed",
                        value=50,
                        min_spend=500,
                        promo_code="KARIBU",
                        starts_at=now - timedelta(days=1),
                    ),
                    Offer(
                        hotel_id=hotel.id,
                        title="Pilau Friday: 10% off",
                        product_id=pilau.id,
                        starts_at=now - timedelta(days=1),
                    ),
                ]
            )
        created.append(slug)
    await session.commit()
    return created
