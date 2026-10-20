"""Read models for the catalogue: product lists with options (no N+1) and the public menu."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Category,
    Discount,
    ExtraGroup,
    ExtraItem,
    Hotel,
    HotelHours,
    Product,
    ProductExtraGroup,
    ProductOption,
)
from app.schemas.catalogue import (
    MenuCategory,
    MenuExtraGroup,
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


@dataclass
class OptionRow:
    """One extra a dish offers: a hotel-wide shared one (group_id set) or this dish's own."""

    id: uuid.UUID
    group_name: str
    name: str
    price_delta: int
    sort_order: int = 0
    is_archived: bool = False
    is_sold_out: bool = False
    group_id: uuid.UUID | None = None


@dataclass
class GroupRow:
    """A dish's group of extras with its rules. Dish-only extras (group_id None) are optional."""

    name: str
    id: uuid.UUID | None = None
    min_picks: int = 0
    max_picks: int | None = None
    is_archived: bool = False
    options: list[OptionRow] = field(default_factory=list)

    @property
    def required_now(self) -> int:
        """Fewest picks needed today: a required group whose extras are all finished can't block
        the dish."""
        free = sum(1 for o in self.options if not o.is_archived and not o.is_sold_out)
        return min(self.min_picks, free)


async def extras_by_product(
    session: AsyncSession, product_ids: list[uuid.UUID], *, include_archived: bool
) -> dict[uuid.UUID, list[GroupRow]]:
    """Every group of extras each dish offers: its own, then the shared ones attached to it."""
    out: dict[uuid.UUID, list[GroupRow]] = {pid: [] for pid in product_ids}
    if not product_ids:
        return out
    stmt = select(ProductOption).where(ProductOption.product_id.in_(product_ids))
    if not include_archived:
        stmt = stmt.where(ProductOption.is_archived.is_(False))
    stmt = stmt.order_by(ProductOption.group_name, ProductOption.sort_order, ProductOption.name)
    own: dict[tuple[uuid.UUID, str], GroupRow] = {}
    for o in (await session.execute(stmt)).scalars():
        g = own.get((o.product_id, o.group_name))
        if g is None:
            g = own[(o.product_id, o.group_name)] = GroupRow(name=o.group_name)
            out[o.product_id].append(g)
        g.options.append(
            OptionRow(o.id, o.group_name, o.name, o.price_delta, o.sort_order, o.is_archived)
        )

    links = (
        await session.execute(
            select(ProductExtraGroup.product_id, ExtraGroup)
            .join(ExtraGroup, ExtraGroup.id == ProductExtraGroup.group_id)
            .where(ProductExtraGroup.product_id.in_(product_ids))
            .order_by(ProductExtraGroup.sort_order, ExtraGroup.sort_order, ExtraGroup.name)
        )
    ).all()
    if not include_archived:
        links = [(pid, g) for pid, g in links if not g.is_archived]
    group_ids = {g.id for _, g in links}
    items: dict[uuid.UUID, list[ExtraItem]] = {gid: [] for gid in group_ids}
    if group_ids:
        stmt = (
            select(ExtraItem)
            .where(ExtraItem.group_id.in_(group_ids))
            .order_by(ExtraItem.sort_order, ExtraItem.name)
        )
        if not include_archived:
            stmt = stmt.where(ExtraItem.is_archived.is_(False))
        for it in (await session.execute(stmt)).scalars():
            items[it.group_id].append(it)
    for pid, g in links:
        out[pid].append(
            GroupRow(
                name=g.name,
                id=g.id,
                min_picks=g.min_picks,
                max_picks=g.max_picks,
                is_archived=g.is_archived,
                options=[
                    OptionRow(
                        it.id,
                        g.name,
                        it.name,
                        it.price_delta,
                        it.sort_order,
                        it.is_archived or g.is_archived,
                        it.is_sold_out,
                        g.id,
                    )
                    for it in items[g.id]
                ],
            )
        )
    return out


async def options_by_product(
    session: AsyncSession, product_ids: list[uuid.UUID], *, include_archived: bool
) -> dict[uuid.UUID, list[OptionRow]]:
    """The same extras as one flat list (what older apps read)."""
    groups = await extras_by_product(session, product_ids, include_archived=include_archived)
    return {pid: [o for g in gs for o in g.options] for pid, gs in groups.items()}


async def attached_group_ids(
    session: AsyncSession, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    out: dict[uuid.UUID, list[uuid.UUID]] = {pid: [] for pid in product_ids}
    if product_ids:
        rows = await session.execute(
            select(ProductExtraGroup.product_id, ProductExtraGroup.group_id)
            .where(ProductExtraGroup.product_id.in_(product_ids))
            .order_by(ProductExtraGroup.sort_order)
        )
        for pid, gid in rows.all():
            out[pid].append(gid)
    return out


def menu_groups(groups: list[GroupRow]) -> list[MenuExtraGroup]:
    return [
        MenuExtraGroup(
            id=g.id,
            name=g.name,
            min_picks=g.required_now,
            max_picks=g.max_picks,
            options=[MenuOption.model_validate(o) for o in g.options],
        )
        for g in groups
        if g.options
    ]


def product_out(
    p: Product, options: list[OptionRow], storage: Storage, extra_group_ids: list[uuid.UUID] = ()
) -> ProductOut:
    return ProductOut(
        id=p.id,
        category_id=p.category_id,
        name=p.name,
        description=p.description,
        price=p.price,
        prep_minutes=p.prep_minutes,
        is_sold_out=p.is_sold_out,
        sold_out_until=p.sold_out_until,
        is_archived=p.is_archived,
        image_url=_url(storage, p.image_key),
        thumb_url=_url(storage, p.thumb_key),
        options=[OptionOut.model_validate(o) for o in options],
        extra_group_ids=list(extra_group_ids),
    )


async def hotel_hours(session: AsyncSession, hotel_ids: list[uuid.UUID]):
    rows = (
        await session.execute(select(HotelHours).where(HotelHours.hotel_id.in_(hotel_ids)))
    ).scalars()
    out: dict[uuid.UUID, list[HotelHours]] = {hid: [] for hid in hotel_ids}
    for h in rows:
        out[h.hotel_id].append(h)
    return out


def next_opening(hours: list[HotelHours], now: datetime) -> datetime:
    """When the store next opens after today (Kenya time): the start of "back tomorrow".

    Falls back to 04:00 tomorrow when no opening hours are set.
    """
    eat = timedelta(hours=3)
    today = (now + eat).date()
    by_day = {h.weekday: h.opens_at for h in hours}
    for ahead in range(1, 8):
        day = today + timedelta(days=ahead)
        if day.weekday() in by_day:
            return datetime.combine(day, by_day[day.weekday()], tzinfo=UTC) - eat
    return datetime.combine(today + timedelta(days=1), time(4), tzinfo=UTC) - eat


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
        kind=hotel.kind,
        phone=hotel.phone,
        accent_color=hotel.accent_color,
        cover_url=_url(storage, hotel.cover_image_key),
        is_open=status.is_open,
        state=status.state,
        closes_at=status.closes_at,
        opens_at=status.opens_at,
        cash_pickup_enabled=False,  # D34: cash on pickup is no longer offered
        verified=hotel.verified_at is not None,
        till_name=hotel.till_name,
        lat=hotel.lat,
        lng=hotel.lng,
        busy_extra_minutes=hotel.busy_extra_minutes,
        prep_minutes=prep_minutes + hotel.busy_extra_minutes,
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
    extras = await extras_by_product(session, [p.id for p in products], include_archived=False)
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
                options=[MenuOption.model_validate(o) for g in extras[p.id] for o in g.options],
                extra_groups=menu_groups(extras[p.id]),
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
