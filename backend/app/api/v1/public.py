"""Customer endpoints: no login."""

import hashlib
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Session
from app.core.errors import AppError, not_found
from app.core.time import utcnow
from app.models import Category, Hotel, Offer, Product
from app.schemas.catalogue import Menu, PublicHotel, PublicOffer, SearchHit
from app.services import catalogue, media, ratings, settings
from app.services.media import Storage

router = APIRouter(tags=["public"])

StorageDep = Annotated[Storage, Depends(media.get_storage)]

# Where the customer is (optional). Both or neither; the radius defaults to the platform setting.
Lat = Annotated[float | None, Query(ge=-90, le=90)]
Lng = Annotated[float | None, Query(ge=-180, le=180)]
RadiusKm = Annotated[float | None, Query(gt=0, le=200)]


async def _nearby_ids(
    session: AsyncSession, lat: float | None, lng: float | None, radius_km: float | None
) -> dict[uuid.UUID, float] | None:
    """Hotel id -> straight-line km, for hotels with a map location inside the radius.
    None means no location was sent (no filtering). Hotels without a location are left out."""
    if (lat is None) != (lng is None):
        raise AppError(422, "bad_location", "Send both lat and lng, or neither")
    if lat is None:
        return None
    values, _ = await settings.load(session)
    limit = radius_km or values.nearby_radius_km
    rows = (
        await session.execute(select(Hotel.id, Hotel.lat, Hotel.lng).where(Hotel.lat.is_not(None)))
    ).all()
    found = {i: settings.distance_km(lat, lng, la, ln) for i, la, ln in rows}
    return {i: km for i, km in found.items() if km <= limit}


@router.get("/hotels", response_model=list[PublicHotel])
async def list_hotels(
    session: Session, storage: StorageDep, lat: Lat = None, lng: Lng = None, radius_km: RadiusKm = None
):
    near = await _nearby_ids(session, lat, lng, radius_km)
    stmt = select(Hotel).order_by(Hotel.name)
    if near is not None:
        stmt = stmt.where(Hotel.id.in_(list(near)))
    hotels = (await session.execute(stmt)).scalars().all()
    values, _ = await settings.load(session)
    hours = await catalogue.hotel_hours(session, [h.id for h in hotels])
    prep = await catalogue.typical_prep(session, [h.id for h in hotels])
    now = utcnow()
    stars = await ratings.hotel_stars(session, [h.id for h in hotels])
    out = []
    for h in hotels:
        card = catalogue.public_hotel(
            h, hours[h.id], now, values.order_cutoff_minutes, storage, prep[h.id]
        )
        card.rating, card.rating_count = stars[h.id].average, stars[h.id].count
        if near is not None:
            card.distance_km = round(near[h.id], 1)
            card.pickup_only = near[h.id] > values.max_delivery_km
        out.append((card, stars[h.id].rank_score))
    if near is not None:
        # Near you: open hotels first, then the closest, then the best rated.
        out.sort(key=lambda c: (not c[0].is_open, c[0].distance_km, -c[1], c[0].name))
    else:
        # Open hotels first, then the best rated, then by name.
        out.sort(key=lambda c: (not c[0].is_open, -c[1], c[0].name))
    return [c for c, _ in out]


@router.get("/hotels/{slug}/menu", response_model=Menu)
async def get_menu(
    slug: str,
    session: Session,
    storage: StorageDep,
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
):
    hotel = (await session.execute(select(Hotel).where(Hotel.slug == slug))).scalar_one_or_none()
    if hotel is None:
        raise not_found("Hotel not found")
    values, _ = await settings.load(session)
    now = utcnow()
    hours = (await catalogue.hotel_hours(session, [hotel.id]))[hotel.id]
    prep = (await catalogue.typical_prep(session, [hotel.id]))[hotel.id]
    menu = Menu(
        hotel=catalogue.public_hotel(hotel, hours, now, values.order_cutoff_minutes, storage, prep),
        categories=await catalogue.menu_categories(session, hotel.id, now, storage),
    )
    # Open/closed state is part of the body, so the ETag changes a few times a day at most.
    body = menu.model_dump_json()
    etag = '"' + hashlib.sha256(body.encode()).hexdigest()[:32] + '"'
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "no-cache"
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    return menu


@router.get("/search", response_model=list[SearchHit])
async def search_dishes(
    session: Session,
    storage: StorageDep,
    q: Annotated[str, Query(max_length=60)] = "",
    lat: Lat = None,
    lng: Lng = None,
    radius_km: RadiusKm = None,
):
    """Keyword search across active hotels' live menus (dish, description or category).
    With the customer's location, only hotels within the radius are searched."""
    near = await _nearby_ids(session, lat, lng, radius_km)
    words = [w for w in q.lower().split() if w][:5]
    if not words:
        return []
    stmt = (
        select(Product, Category, Hotel)
        .join(Category, Category.id == Product.category_id)
        .join(Hotel, Hotel.id == Product.hotel_id)
        .where(Hotel.status == "active", Product.is_archived.is_(False))
    )
    if near is not None:
        stmt = stmt.where(Hotel.id.in_(list(near)))
    for w in words:
        like = f"%{w.replace('%', '').replace('_', '')}%"
        stmt = stmt.where(
            or_(Product.name.ilike(like), Product.description.ilike(like), Category.name.ilike(like))
        )
    rows = (await session.execute(stmt.order_by(Product.is_sold_out, Product.name).limit(60))).all()
    return [
        SearchHit(
            hotel_slug=h.slug,
            hotel_name=h.name,
            product_id=p.id,
            name=p.name,
            category=c.name,
            price=p.price,
            is_sold_out=p.is_sold_out,
            thumb_url=storage.url(p.thumb_key) if p.thumb_key else None,
        )
        for p, c, h in rows
    ]


@router.get("/offers", response_model=list[PublicOffer])
async def list_offers(
    session: Session, storage: StorageDep, lat: Lat = None, lng: Lng = None, radius_km: RadiusKm = None
):
    near = await _nearby_ids(session, lat, lng, radius_km)
    now = utcnow()
    stmt = (
        select(Offer, Hotel)
        .join(Hotel, Hotel.id == Offer.hotel_id)
        .where(
            Hotel.status == "active",
            Offer.starts_at <= now,
            or_(Offer.ends_at.is_(None), Offer.ends_at > now),
        )
        .order_by(Offer.sort_order, Offer.starts_at)
    )
    if near is not None:
        stmt = stmt.where(Hotel.id.in_(list(near)))
    rows = (await session.execute(stmt)).all()
    return [
        PublicOffer(
            id=o.id,
            hotel_slug=h.slug,
            hotel_name=h.name,
            title=o.title,
            image_url=storage.url(o.image_key) if o.image_key else None,
            product_id=o.product_id,
            ends_at=o.ends_at,
        )
        for o, h in rows
    ]


@router.get("/config")
async def public_config(session: Session):
    """What the customer app needs before checkout: the delivery zone (drawn by the admin)."""
    values, _ = await settings.load(session)
    return {
        "delivery_zone": [],  # no drawn area any more: delivery is by distance from the hotel
        # Without a drawn area, hotels with a location deliver up to max_delivery_km.
        "delivery_available": True,
        "rider_fee": values.base_rider_fee,  # "from" price before a pin is dropped
        "rider_fee_bands": [b.model_dump() for b in values.rider_fee_bands],
        "max_delivery_km": values.max_delivery_km,
        "nearby_radius_km": values.nearby_radius_km,
        "delivery_mode": "distance",
        "support_whatsapp": values.support_whatsapp or None,
    }
