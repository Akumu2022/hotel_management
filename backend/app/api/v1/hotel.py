"""Hotel area. Every query is scoped to the caller's hotel (see deps.scoped_select).

Hotel admins manage the catalogue; cashiers can read it and flip only "sold out" and
"accepting orders", which counter staff need during service.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import (
    HotelAdmin,
    HotelStaff,
    Session,
    get_scoped,
    scoped_select,
)
from app.core.errors import AppError, not_found
from app.core.security import hash_password
from app.models import (
    Category,
    Discount,
    Hotel,
    HotelHours,
    Offer,
    Order,
    Product,
    ProductOption,
    PromoRedemption,
    User,
)
from app.schemas.admin import UserOut
from app.schemas.auth import CashierIn, StaffActiveIn, TempPasswordOut
from app.schemas.catalogue import (
    CategoryIn,
    CategoryOut,
    CategoryPatch,
    DayHours,
    DiscountIn,
    DiscountOut,
    DiscountPatch,
    HotelSettingsIn,
    HotelSettingsOut,
    OfferIn,
    OfferOut,
    OfferPatch,
    OptionIn,
    OptionOut,
    OptionPatch,
    ProductIn,
    ProductOut,
    ProductPatch,
    UploadOut,
)
from app.services import audit, catalogue, media
from app.services.auth import reset_password, revoke_all
from app.services.media import Storage
from app.services.settings import percent_to_bp

router = APIRouter(prefix="/hotel", tags=["hotel"])

StorageDep = Annotated[Storage, Depends(media.get_storage)]


def _duplicate(what: str) -> AppError:
    return AppError(409, "duplicate", f"A {what} with that name already exists")


def _own_image_key(hotel_id: uuid.UUID, key: str | None) -> None:
    """Image keys come from our own upload endpoint; never accept another hotel's file."""
    if key is not None and not key.startswith(f"hotels/{hotel_id}/"):
        raise AppError(422, "bad_image_key", "Upload the photo first")


def _thumb_for(key: str | None) -> str | None:
    return key[: -len(".webp")] + "-thumb.webp" if key else None


# --- Categories -------------------------------------------------------------------------------


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(user: HotelStaff, session: Session):
    stmt = scoped_select(Category, user.hotel_id).order_by(Category.sort_order, Category.name)
    return (await session.execute(stmt)).scalars().all()


@router.get("/categories/{category_id}", response_model=CategoryOut)
async def get_category(category_id: uuid.UUID, user: HotelStaff, session: Session):
    return await get_scoped(session, Category, category_id, user.hotel_id)


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(body: CategoryIn, user: HotelAdmin, session: Session):
    category = Category(hotel_id=user.hotel_id, **body.model_dump())
    session.add(category)
    try:
        await session.flush()
    except IntegrityError:
        raise _duplicate("category") from None
    await session.commit()
    return category


@router.patch("/categories/{category_id}", response_model=CategoryOut)
async def patch_category(
    category_id: uuid.UUID, body: CategoryPatch, user: HotelAdmin, session: Session
):
    category = await get_scoped(session, Category, category_id, user.hotel_id)
    for key, value in body.model_dump(exclude_unset=True).items():
        if key == "name" and value is None:
            raise AppError(422, "validation_error", "name cannot be empty")
        setattr(category, key, value)
    if (category.available_from is None) != (category.available_to is None):
        raise AppError(422, "validation_error", "Set both 'available from' and 'available to'")
    try:
        await session.flush()
    except IntegrityError:
        raise _duplicate("category") from None
    await session.commit()
    return category


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(category_id: uuid.UUID, user: HotelAdmin, session: Session):
    category = await get_scoped(session, Category, category_id, user.hotel_id)
    in_use = await session.scalar(
        select(func.count()).select_from(Product).where(Product.category_id == category.id)
    )
    if in_use:
        raise AppError(409, "category_in_use", "Move or archive its products first")
    await session.delete(category)
    await session.commit()


# --- Products ---------------------------------------------------------------------------------


async def _product_out(session, product: Product, storage: Storage) -> ProductOut:
    opts = await catalogue.options_by_product(session, [product.id], include_archived=True)
    return catalogue.product_out(product, opts[product.id], storage)


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    user: HotelStaff,
    session: Session,
    storage: StorageDep,
    category_id: uuid.UUID | None = None,
    include_archived: bool = False,
):
    stmt = scoped_select(Product, user.hotel_id).order_by(Product.name)
    if category_id:
        stmt = stmt.where(Product.category_id == category_id)
    if not include_archived:
        stmt = stmt.where(Product.is_archived.is_(False))
    products = (await session.execute(stmt)).scalars().all()
    opts = await catalogue.options_by_product(
        session, [p.id for p in products], include_archived=True
    )
    return [catalogue.product_out(p, opts[p.id], storage) for p in products]


@router.get("/products/{product_id}", response_model=ProductOut)
async def get_product(
    product_id: uuid.UUID, user: HotelStaff, session: Session, storage: StorageDep
):
    product = await get_scoped(session, Product, product_id, user.hotel_id)
    return await _product_out(session, product, storage)


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(body: ProductIn, user: HotelAdmin, session: Session, storage: StorageDep):
    await get_scoped(session, Category, body.category_id, user.hotel_id)
    _own_image_key(user.hotel_id, body.image_key)
    data = body.model_dump()
    product = Product(hotel_id=user.hotel_id, thumb_key=_thumb_for(body.image_key), **data)
    session.add(product)
    await session.commit()
    return await _product_out(session, product, storage)


_CASHIER_PRODUCT_FIELDS = {"is_sold_out"}


@router.patch("/products/{product_id}", response_model=ProductOut)
async def patch_product(
    product_id: uuid.UUID,
    body: ProductPatch,
    user: HotelStaff,
    session: Session,
    storage: StorageDep,
):
    data = body.model_dump(exclude_unset=True)
    if user.role != "hotel_admin" and set(data) - _CASHIER_PRODUCT_FIELDS:
        raise AppError(403, "forbidden", "Only the hotel admin can edit products")
    product = await get_scoped(session, Product, product_id, user.hotel_id)
    if data.get("category_id"):
        await get_scoped(session, Category, data["category_id"], user.hotel_id)
    if "image_key" in data:
        _own_image_key(user.hotel_id, data["image_key"])
        product.thumb_key = _thumb_for(data["image_key"])
    for key, value in data.items():
        if value is None and key != "image_key":
            raise AppError(422, "validation_error", f"{key} cannot be empty")
        setattr(product, key, value)
    await session.commit()
    return await _product_out(session, product, storage)


# --- Options ----------------------------------------------------------------------------------


@router.get("/products/{product_id}/options", response_model=list[OptionOut])
async def list_options(product_id: uuid.UUID, user: HotelStaff, session: Session):
    product = await get_scoped(session, Product, product_id, user.hotel_id)
    opts = await catalogue.options_by_product(session, [product.id], include_archived=True)
    return opts[product.id]


@router.post("/products/{product_id}/options", response_model=OptionOut, status_code=201)
async def create_option(product_id: uuid.UUID, body: OptionIn, user: HotelAdmin, session: Session):
    product = await get_scoped(session, Product, product_id, user.hotel_id)
    option = ProductOption(product_id=product.id, **body.model_dump())
    session.add(option)
    await session.commit()
    return option


@router.patch("/products/{product_id}/options/{option_id}", response_model=OptionOut)
async def patch_option(
    product_id: uuid.UUID,
    option_id: uuid.UUID,
    body: OptionPatch,
    user: HotelAdmin,
    session: Session,
):
    product = await get_scoped(session, Product, product_id, user.hotel_id)
    option = await session.get(ProductOption, option_id)
    if option is None or option.product_id != product.id:
        raise not_found()
    for key, value in body.model_dump(exclude_unset=True).items():
        if value is None:
            raise AppError(422, "validation_error", f"{key} cannot be empty")
        setattr(option, key, value)
    await session.commit()
    return option


# --- Uploads ----------------------------------------------------------------------------------


@router.post("/uploads/image", response_model=UploadOut, status_code=201)
async def upload_image(user: HotelAdmin, storage: StorageDep, file: Annotated[UploadFile, File()]):
    data = await file.read(media.MAX_UPLOAD_BYTES + 1)
    image_key, thumb_key = media.save_image(storage, user.hotel_id, data)
    return UploadOut(
        image_key=image_key,
        thumb_key=thumb_key,
        image_url=storage.url(image_key),
        thumb_url=storage.url(thumb_key),
    )


# --- Discounts --------------------------------------------------------------------------------


async def _discount_out(session, discounts: list[Discount]) -> list[DiscountOut]:
    ids = [d.id for d in discounts]
    uses = (
        dict(
            (
                await session.execute(
                    select(PromoRedemption.discount_id, func.count())
                    .where(PromoRedemption.discount_id.in_(ids))
                    .group_by(PromoRedemption.discount_id)
                )
            ).all()
        )
        if ids
        else {}
    )
    out = []
    for d in discounts:
        item = DiscountOut.model_validate(d)
        item.uses = uses.get(d.id, 0)
        out.append(item)
    return out


@router.get("/discounts", response_model=list[DiscountOut])
async def list_discounts(user: HotelStaff, session: Session):
    stmt = scoped_select(Discount, user.hotel_id).order_by(Discount.created_at.desc())
    return await _discount_out(session, list((await session.execute(stmt)).scalars().all()))


@router.post("/discounts", response_model=DiscountOut, status_code=201)
async def create_discount(body: DiscountIn, user: HotelAdmin, session: Session):
    if body.product_id:
        await get_scoped(session, Product, body.product_id, user.hotel_id)
    value = percent_to_bp(body.percent) if body.kind == "percent" else body.amount
    discount = Discount(
        hotel_id=user.hotel_id,
        scope=body.scope,
        product_id=body.product_id,
        kind=body.kind,
        value=value,
        min_spend=body.min_spend,
        promo_code=body.promo_code,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        max_uses=body.max_uses,
        is_active=body.is_active,
        days_mask=body.days_mask,
        daily_from=body.daily_from,
        daily_to=body.daily_to,
    )
    session.add(discount)
    try:
        await session.flush()
    except IntegrityError:
        raise AppError(409, "duplicate", "That promo code is already in use") from None
    await session.commit()
    return (await _discount_out(session, [discount]))[0]


@router.patch("/discounts/{discount_id}", response_model=DiscountOut)
async def patch_discount(
    discount_id: uuid.UUID, body: DiscountPatch, user: HotelAdmin, session: Session
):
    discount = await get_scoped(session, Discount, discount_id, user.hotel_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("is_active") is None:
        data.pop("is_active", None)
    for key, value in data.items():
        setattr(discount, key, value)
    if discount.ends_at is not None and discount.ends_at <= discount.starts_at:
        raise AppError(422, "validation_error", "The end must be after the start")
    if discount.max_uses is not None and discount.promo_code is None:
        raise AppError(422, "validation_error", "A total use limit only applies to promo codes")
    await session.commit()
    return (await _discount_out(session, [discount]))[0]


# --- Offers -----------------------------------------------------------------------------------


def _offer_out(offer: Offer, storage: Storage) -> OfferOut:
    out = OfferOut.model_validate(offer)
    out.image_url = storage.url(offer.image_key) if offer.image_key else None
    return out


async def _check_offer_refs(session, hotel_id, product_id, discount_id, image_key) -> None:
    if product_id:
        await get_scoped(session, Product, product_id, hotel_id)
    if discount_id:
        await get_scoped(session, Discount, discount_id, hotel_id)
    _own_image_key(hotel_id, image_key)


@router.get("/offers", response_model=list[OfferOut])
async def list_offers(user: HotelStaff, session: Session, storage: StorageDep):
    stmt = scoped_select(Offer, user.hotel_id).order_by(Offer.sort_order, Offer.starts_at)
    return [_offer_out(o, storage) for o in (await session.execute(stmt)).scalars()]


@router.post("/offers", response_model=OfferOut, status_code=201)
async def create_offer(body: OfferIn, user: HotelAdmin, session: Session, storage: StorageDep):
    await _check_offer_refs(
        session, user.hotel_id, body.product_id, body.discount_id, body.image_key
    )
    offer = Offer(hotel_id=user.hotel_id, **body.model_dump())
    session.add(offer)
    await session.commit()
    return _offer_out(offer, storage)


@router.patch("/offers/{offer_id}", response_model=OfferOut)
async def patch_offer(
    offer_id: uuid.UUID, body: OfferPatch, user: HotelAdmin, session: Session, storage: StorageDep
):
    offer = await get_scoped(session, Offer, offer_id, user.hotel_id)
    data = body.model_dump(exclude_unset=True)
    await _check_offer_refs(
        session,
        user.hotel_id,
        data.get("product_id"),
        data.get("discount_id"),
        data.get("image_key"),
    )
    for key, value in data.items():
        if value is None and key in ("title", "starts_at", "sort_order"):
            raise AppError(422, "validation_error", f"{key} cannot be empty")
        setattr(offer, key, value)
    if offer.ends_at is not None and offer.ends_at <= offer.starts_at:
        raise AppError(422, "validation_error", "The end must be after the start")
    await session.commit()
    return _offer_out(offer, storage)


@router.delete("/offers/{offer_id}", status_code=204)
async def delete_offer(offer_id: uuid.UUID, user: HotelAdmin, session: Session):
    offer = await get_scoped(session, Offer, offer_id, user.hotel_id)
    await session.delete(offer)
    await session.commit()


# --- Hotel settings ---------------------------------------------------------------------------


async def _settings_out(session, hotel: Hotel, storage: Storage) -> HotelSettingsOut:
    hours = (
        (
            await session.execute(
                select(HotelHours)
                .where(HotelHours.hotel_id == hotel.id)
                .order_by(HotelHours.weekday)
            )
        )
        .scalars()
        .all()
    )
    return HotelSettingsOut(
        name=hotel.name,
        phone=hotel.phone,
        till_number=hotel.till_number,
        cash_pickup_enabled=hotel.cash_pickup_enabled,
        accepting_orders=hotel.accepting_orders,
        status=hotel.status,
        accent_color=hotel.accent_color,
        cover_url=storage.url(hotel.cover_image_key) if hotel.cover_image_key else None,
        hours=[
            DayHours(weekday=h.weekday, opens_at=h.opens_at, closes_at=h.closes_at) for h in hours
        ],
        lat=hotel.lat,
        lng=hotel.lng,
    )


@router.get("/settings", response_model=HotelSettingsOut)
async def get_settings(user: HotelStaff, session: Session, storage: StorageDep):
    hotel = await session.get(Hotel, user.hotel_id)
    return await _settings_out(session, hotel, storage)


_CASHIER_SETTINGS_FIELDS = {"accepting_orders"}
IDENTITY = ("name", "phone", "till_number")


@router.put("/settings", response_model=HotelSettingsOut)
async def put_settings(
    body: HotelSettingsIn, user: HotelStaff, session: Session, storage: StorageDep
):
    data = body.model_dump(exclude_unset=True)
    if user.role != "hotel_admin" and set(data) - _CASHIER_SETTINGS_FIELDS:
        raise AppError(403, "forbidden", "Only the hotel admin can change these settings")
    hotel = await session.get(Hotel, user.hotel_id, with_for_update=True)
    hours = data.pop("hours", None)
    if "cover_image_key" in data:
        _own_image_key(hotel.id, data["cover_image_key"])
    identity = {}
    for key, value in data.items():
        if value is None and key in ("cash_pickup_enabled", "accepting_orders", *IDENTITY):
            raise AppError(422, "validation_error", f"{key} cannot be empty")
        if key in IDENTITY and getattr(hotel, key) != value:
            identity[key] = {"old": getattr(hotel, key), "new": value}
    if "till_number" in identity:
        # Customers still paying were shown the old Till: changing it now would strand them.
        paying = await session.scalar(
            select(func.count())
            .select_from(Order)
            .where(
                Order.hotel_id == hotel.id,
                Order.status.in_(("awaiting_payment", "checking_payment")),
                Order.payment_method == "mpesa",
            )
        )
        if paying:
            raise AppError(
                409,
                "orders_paying",
                f"{paying} customer(s) are paying to your current Till. Try once they're done.",
            )
    for key, value in data.items():
        setattr(hotel, key, value)
    if identity:
        try:
            await session.flush()
        except IntegrityError:
            raise AppError(409, "duplicate", "That Till number belongs to another hotel") from None
        await audit.log(
            session,
            actor_id=user.id,
            action="hotel.update",
            target_type="hotel",
            target_id=hotel.id,
            details=identity,
        )
    if hours is not None:
        await session.execute(delete(HotelHours).where(HotelHours.hotel_id == hotel.id))
        session.add_all(HotelHours(hotel_id=hotel.id, **h) for h in hours)
    await session.commit()
    return await _settings_out(session, hotel, storage)


# --- Staff (D28) -------------------------------------------------------------------------------


@router.get("/staff", response_model=list[UserOut])
async def list_staff(user: HotelAdmin, session: Session):
    rows = await session.scalars(
        select(User).where(User.hotel_id == user.hotel_id).order_by(User.role, User.name)
    )
    return [UserOut.model_validate(r) for r in rows]


@router.post("/staff", response_model=UserOut, status_code=201)
async def add_cashier(body: CashierIn, user: HotelAdmin, session: Session):
    cashier = User(
        role="cashier",
        hotel_id=user.hotel_id,
        name=body.name,
        phone=body.phone,
        password_hash=hash_password(body.password),
        must_change_password=True,  # the admin chose it; the cashier picks their own
    )
    session.add(cashier)
    try:
        await session.flush()
    except IntegrityError:
        raise AppError(409, "phone_taken", "That phone number already has a login") from None
    await audit.log(
        session, actor_id=user.id, action="user.create", target_type="user", target_id=cashier.id
    )
    await session.commit()
    await session.refresh(cashier)
    return UserOut.model_validate(cashier)


async def _own_cashier(session, user, staff_id: uuid.UUID) -> User:
    row = await session.get(User, staff_id, with_for_update=True)
    if row is None or row.hotel_id != user.hotel_id or row.role != "cashier":
        raise not_found("Staff member not found")
    return row


@router.patch("/staff/{staff_id}", response_model=UserOut)
async def set_cashier_active(
    staff_id: uuid.UUID, body: StaffActiveIn, user: HotelAdmin, session: Session
):
    row = await _own_cashier(session, user, staff_id)
    row.is_active = body.is_active
    if not body.is_active:
        await revoke_all(session, row.id)
    await audit.log(
        session,
        actor_id=user.id,
        action="user.update",
        target_type="user",
        target_id=row.id,
        details={"is_active": body.is_active},
    )
    await session.commit()
    return UserOut.model_validate(row)


@router.post("/staff/{staff_id}/reset-password", response_model=TempPasswordOut)
async def reset_cashier_password(staff_id: uuid.UUID, user: HotelAdmin, session: Session):
    row = await _own_cashier(session, user, staff_id)
    temp = await reset_password(session, row)
    await audit.log(
        session,
        actor_id=user.id,
        action="user.password_reset",
        target_type="user",
        target_id=row.id,
    )
    await session.commit()
    return TempPasswordOut(temp_password=temp)
