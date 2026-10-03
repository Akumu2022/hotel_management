"""Read models for the catalogue: product lists with options (no N+1) and the public menu."""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Category, Discount, Hotel, HotelHours, Product, ProductOption
from app.schemas.catalogue import (
    MenuCategory,
    MenuOption,
    MenuProduct,
    OptionOut,
    ProductOut,
    PublicHotel,
)
from app.services import hours as hours_service
from app.services.media import Storage
from app.services.pricing import pct


def _url(storage: Storage, key: str | None) -> str | None:
    return storage.url(key) if key else None


async def options_by_product(
    session: AsyncSession, product_ids: list[uuid.UUID], *, include_archived: bool
) -> dict[uuid.UUID, list[ProductOption]]:
    out: dict[uuid.UUID, list[ProductOption]] = {pid: [] for pid in product_ids}
    if not product_ids:
        return out
    stmt = select(ProductOption).where(ProductOption.product_id.in_(product_ids))
    if not include_archived:
        stmt = stmt.where(ProductOption.is_archived.is_(False))
    stmt = stmt.order_by(ProductOption.group_name, ProductOption.sort_order, ProductOption.name)
    for opt in (await session.execute(stmt)).scalars():
        out[opt.product_id].append(opt)
    return out


def product_out(p: Product, options: list[ProductOption], storage: Storage) -> ProductOut:
    return ProductOut(
        id=p.id,
        category_id=p.category_id,
        name=p.name,
        description=p.description,
        price=p.price,
        prep_minutes=p.prep_minutes,
        is_sold_out=p.is_sold_out,
        is_archived=p.is_archived,
        image_url=_url(storage, p.image_key),
        thumb_url=_url(storage, p.thumb_key),
        options=[OptionOut.model_validate(o) for o in options],
    )


async def hotel_hours(session: AsyncSession, hotel_ids: list[uuid.UUID]):
    rows = (
        await session.execute(select(HotelHours).where(HotelHours.hotel_id.in_(hotel_ids)))
    ).scalars()
    out: dict[uuid.UUID, list[HotelHours]] = {hid: [] for hid in hotel_ids}
    for h in rows:
        out[h.hotel_id].append(h)
    return out


async def typical_prep(session: AsyncSession, hotel_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Median prep minutes of each hotel's live dishes (15 when it has none)."""
    rows = await session.execute(
        select(Product.hotel_id, func.percentile_cont(0.5).within_group(Product.prep_minutes))
        .where(Product.hotel_id.in_(hotel_ids), Product.is_archived.is_(False))
        .group_by(Product.hotel_id)
    )
    found = {hid: round(m) for hid, m in rows.all()}
    return {hid: found.get(hid, 15) for hid in hotel_ids}


def public_hotel(
    hotel: Hotel,
    hours: list[HotelHours],
    now: datetime,
    cutoff: int,
    storage: Storage,
    prep_minutes: int = 15,
) -> PublicHotel:
    status = hours_service.open_status(hotel, hours, now, cutoff)
    return PublicHotel(
        slug=hotel.slug,
        name=hotel.name,
        phone=hotel.phone,
        accent_color=hotel.accent_color,
        cover_url=_url(storage, hotel.cover_image_key),
        is_open=status.is_open,
        state=status.state,
        closes_at=status.closes_at,
        opens_at=status.opens_at,
        cash_pickup_enabled=hotel.cash_pickup_enabled,
        lat=hotel.lat,
        lng=hotel.lng,
        prep_minutes=prep_minutes,
    )


def _live(d: Discount, now: datetime) -> bool:
    return d.is_active and d.starts_at <= now and (d.ends_at is None or now < d.ends_at)


async def menu_categories(
    session: AsyncSession, hotel_id: uuid.UUID, now: datetime, storage: Storage
) -> list[MenuCategory]:
    """Visible menu: non-archived products (sold-out ones included, greyed by the app) in
    categories that have at least one such product."""
    categories = (
        (
            await session.execute(
                select(Category)
                .where(Category.hotel_id == hotel_id)
                .order_by(Category.sort_order, Category.name)
            )
        )
        .scalars()
        .all()
    )
    products = (
        (
            await session.execute(
                select(Product)
                .where(Product.hotel_id == hotel_id, Product.is_archived.is_(False))
                .order_by(Product.name)
            )
        )
        .scalars()
        .all()
    )
    options = await options_by_product(session, [p.id for p in products], include_archived=False)
    discounts = (
        (
            await session.execute(
                select(Discount).where(
                    Discount.hotel_id == hotel_id,
                    Discount.scope == "item",
                    Discount.promo_code.is_(None),
                    Discount.min_spend == 0,
                )
            )
        )
        .scalars()
        .all()
    )
    products_by_id = {p.id: p for p in products}
    best_unit: dict[uuid.UUID, int] = {}
    for d in discounts:
        if not _live(d, now):
            continue
        product = products_by_id.get(d.product_id)
        if product is None:
            continue
        off = pct(d.value, product.price) if d.kind == "percent" else d.value
        best_unit[product.id] = max(best_unit.get(product.id, 0), min(off, product.price))

    by_cat: dict[uuid.UUID, list[MenuProduct]] = {c.id: [] for c in categories}
    for p in products:
        off = best_unit.get(p.id, 0)
        by_cat[p.category_id].append(
            MenuProduct(
                id=p.id,
                name=p.name,
                description=p.description,
                price=p.price,
                prep_minutes=p.prep_minutes,
                is_sold_out=p.is_sold_out,
                image_url=_url(storage, p.image_key),
                thumb_url=_url(storage, p.thumb_key),
                options=[MenuOption.model_validate(o) for o in options[p.id]],
                discount_price=p.price - off if off else None,
            )
        )
    return [
        MenuCategory(
            id=c.id,
            name=c.name,
            available_from=c.available_from,
            available_to=c.available_to,
            products=by_cat[c.id],
        )
        for c in categories
        if by_cat[c.id]
    ]
