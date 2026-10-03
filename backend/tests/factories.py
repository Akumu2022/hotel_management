import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password
from app.models import Category, Customer, Hotel, Order, Product, User
from app.services import pricing
from app.services.settings import HotelRates

NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
PASSWORD = "correct-horse-battery"


def _digits(n: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(n))


async def make_hotel(session: AsyncSession, **kw) -> Hotel:
    slug = kw.pop("slug", f"hotel-{uuid.uuid4().hex[:8]}")
    hotel = Hotel(
        name=kw.pop("name", slug.title()),
        slug=slug,
        phone=kw.pop("phone", "2547" + _digits(8)),
        till_number=kw.pop("till_number", _digits(7)),
        **kw,
    )
    session.add(hotel)
    await session.flush()
    return hotel


async def make_user(session: AsyncSession, role: str, hotel: Hotel | None = None, **kw) -> User:
    user = User(
        role=role,
        hotel_id=hotel.id if hotel else None,
        name=kw.pop("name", role.replace("_", " ").title()),
        phone=kw.pop("phone", "2547" + _digits(8)),
        password_hash=hash_password(kw.pop("password", PASSWORD)),
        **kw,
    )
    session.add(user)
    await session.flush()
    return user


def auth_header(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, user.role, user.hotel_id)}"}


async def make_category(session: AsyncSession, hotel: Hotel, name: str = "Mains") -> Category:
    cat = Category(hotel_id=hotel.id, name=name)
    session.add(cat)
    await session.flush()
    return cat


async def make_product(
    session: AsyncSession, hotel: Hotel, price: int = 650, name: str = "Pilau"
) -> Product:
    cat = await make_category(session, hotel, f"Cat {uuid.uuid4().hex[:6]}")
    product = Product(hotel_id=hotel.id, category_id=cat.id, name=name, price=price)
    session.add(product)
    await session.flush()
    return product


async def make_order(
    session: AsyncSession,
    hotel: Hotel,
    *,
    food: int = 650,
    order_type: str = "delivery",
    rider_fee_mode: str = "included",
    rates: HotelRates = HotelRates(commission_bp=1000, service_fee=20, rider_fee=100),
    status: str = "awaiting_payment",
    payment_method: str = "mpesa",
) -> Order:
    """An order priced by the real pricing service (one product line worth `food`)."""
    product = await make_product(session, hotel, price=food)
    quote = pricing.calculate(
        cart=[pricing.CartLine(product_id=product.id, quantity=1)],
        products={product.id: pricing.ProductInfo(product.id, product.name, product.price)},
        discounts=[],
        order_type=order_type,
        rider_fee_mode=rider_fee_mode,
        rates=rates,
        now=NOW,
    )
    phone = "2547" + _digits(8)
    session.add(Customer(phone=phone, name="Test Customer"))
    order = Order(
        code=_digits(8),
        tracking_token=secrets.token_urlsafe(24),
        hotel_id=hotel.id,
        customer_phone=phone,
        customer_name="Test Customer",
        type=order_type,
        rider_fee_mode=rider_fee_mode,
        payment_method=payment_method,
        status=status,
        lat=-1.28 if order_type == "delivery" else None,
        lng=36.82 if order_type == "delivery" else None,
        items_total=quote.items_total,
        order_discount=quote.order_discount,
        food_net=quote.food_net,
        service_fee=quote.service_fee,
        rider_fee=quote.rider_fee,
        rider_fee_in_till=quote.rider_fee_in_till,
        till_amount=quote.till_amount,
        commission_bp=quote.commission_bp,
        commission_amount=quote.commission_amount,
        delivery_code=f"{secrets.randbelow(10_000):04d}" if order_type == "delivery" else None,
    )
    session.add(order)
    await session.flush()
    return order
