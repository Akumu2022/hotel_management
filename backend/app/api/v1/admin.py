import uuid

from fastapi import APIRouter
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import Session, SuperAdmin
from app.api.pagination import paginate
from app.core.errors import AppError, not_found
from app.core.security import hash_password
from app.models import Hotel, User
from app.schemas.admin import (
    HotelCreate,
    HotelOut,
    HotelPatch,
    SettingsIn,
    SettingsOut,
    UserCreate,
    UserOut,
    UserPatch,
    hotel_values,
)
from app.schemas.auth import TempPasswordOut
from app.schemas.common import Page
from app.services import audit, ratings, routing, settings
from app.services.auth import reset_password, revoke_all

router = APIRouter(prefix="/admin", tags=["admin"])


# --- Settings ----------------------------------------------------------------------------


@router.get("/settings", response_model=SettingsOut)
async def get_settings(_: SuperAdmin, session: Session):
    values, reviewed = await settings.load(session)
    return SettingsOut.build(values, reviewed)


@router.put("/settings", response_model=SettingsOut)
async def put_settings(body: SettingsIn, admin: SuperAdmin, session: Session):
    try:
        values = await settings.update(session, body.to_changes(), admin.id)
    except ValidationError as e:
        raise AppError(422, "validation_error", e.errors()[0]["msg"]) from None
    except ValueError as e:
        raise AppError(422, "validation_error", str(e)) from None
    await session.commit()
    return SettingsOut.build(values, reviewed=True)


@router.get("/distance")
async def distance_check(
    _: SuperAdmin, session: Session, hotel_id: uuid.UUID, lat: float, lng: float
):
    """Admin calculator: the same distance and fee a customer at (lat, lng) would get."""
    hotel = await session.get(Hotel, hotel_id)
    if hotel is None:
        raise not_found("Hotel not found")
    if hotel.lat is None:
        raise AppError(409, "no_location", f"Place {hotel.name} on the map first")
    values, _ = await settings.load(session)
    d = await routing.distance(hotel.lat, hotel.lng, lat, lng, values.distance_method)
    straight = round(settings.distance_km(hotel.lat, hotel.lng, lat, lng), 1)
    fee = values.rider_fee_at(d.km)
    return {
        "distance_km": d.km,
        "method": d.method,
        "straight_km": straight,
        "rider_fee": fee,
        "too_far": fee is None,
        "max_delivery_km": values.max_delivery_km,
    }


# --- Hotels -----------------------------------------------------------------------------------


def _unique_violation(e: IntegrityError) -> AppError:
    msg = str(e.orig)
    for field in ("slug", "till_number", "phone"):
        if field in msg:
            return AppError(409, "duplicate", f"That {field.replace('_', ' ')} is already in use")
    return AppError(409, "conflict", "That conflicts with an existing record")


@router.get("/hotels", response_model=Page[HotelOut])
async def list_hotels(_: SuperAdmin, session: Session, cursor: str | None = None, limit: int = 50):
    rows, next_cursor = await paginate(session, select(Hotel), Hotel, cursor, limit)
    stars = await ratings.hotel_stars(session, [r.id for r in rows])
    items = []
    for r in rows:
        out = HotelOut.model_validate(r)
        out.rating, out.rating_count = stars[r.id].average, stars[r.id].count
        items.append(out)
    return Page[HotelOut](items=items, next_cursor=next_cursor)


@router.post("/hotels", response_model=HotelOut, status_code=201)
async def create_hotel(body: HotelCreate, admin: SuperAdmin, session: Session):
    """Only the owner creates hotels, optionally with the hotel admin's login, who must
    choose their own password at first login."""
    hotel = Hotel(**hotel_values(body))
    session.add(hotel)
    try:
        await session.flush()
        if body.admin is not None:
            session.add(
                User(
                    role="hotel_admin",
                    hotel_id=hotel.id,
                    name=body.admin.name,
                    phone=body.admin.phone,
                    password_hash=hash_password(body.admin.password),
                    must_change_password=True,
                )
            )
            await session.flush()
    except IntegrityError as e:
        raise _unique_violation(e) from None
    await audit.log(
        session,
        actor_id=admin.id,
        action="hotel.create",
        target_type="hotel",
        target_id=hotel.id,
        details=body.model_dump(mode="json", exclude={"admin": {"password"}}),
    )
    await session.commit()
    await session.refresh(hotel)
    return HotelOut.model_validate(hotel)


@router.patch("/hotels/{hotel_id}", response_model=HotelOut)
async def patch_hotel(hotel_id: uuid.UUID, body: HotelPatch, admin: SuperAdmin, session: Session):
    hotel = await session.get(Hotel, hotel_id, with_for_update=True)
    if hotel is None:
        raise not_found("Hotel not found")
    changes = {}
    for key, value in hotel_values(body).items():
        old = getattr(hotel, key)
        if old != value:
            changes[key] = {"old": old, "new": value}
            setattr(hotel, key, value)
    try:
        await session.flush()
    except IntegrityError as e:
        raise _unique_violation(e) from None
    if changes:
        await audit.log(
            session,
            actor_id=admin.id,
            action="hotel.update",
            target_type="hotel",
            target_id=hotel.id,
            details=changes,
        )
    await session.commit()
    await session.refresh(hotel)
    return HotelOut.model_validate(hotel)


# --- Users ------------------------------------------------------------------------------------


@router.get("/users", response_model=Page[UserOut])
async def list_users(
    _: SuperAdmin,
    session: Session,
    role: str | None = None,
    hotel_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: int = 50,
):
    stmt = select(User)
    if role:
        stmt = stmt.where(User.role == role)
    if hotel_id:
        stmt = stmt.where(User.hotel_id == hotel_id)
    rows, next_cursor = await paginate(session, stmt, User, cursor, limit)
    return Page[UserOut](items=[UserOut.model_validate(r) for r in rows], next_cursor=next_cursor)


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, admin: SuperAdmin, session: Session):
    if body.hotel_id and await session.get(Hotel, body.hotel_id) is None:
        raise not_found("Hotel not found")
    user = User(
        role=body.role,
        hotel_id=body.hotel_id,
        name=body.name,
        phone=body.phone,
        password_hash=hash_password(body.password),
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as e:
        raise _unique_violation(e) from None
    await audit.log(
        session,
        actor_id=admin.id,
        action="user.create",
        target_type="user",
        target_id=user.id,
        details={"role": user.role, "hotel_id": str(user.hotel_id) if user.hotel_id else None},
    )
    await session.commit()
    await session.refresh(user)
    return UserOut.model_validate(user)


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(user_id: uuid.UUID, body: UserPatch, admin: SuperAdmin, session: Session):
    user = await session.get(User, user_id, with_for_update=True)
    if user is None:
        raise not_found("User not found")
    data = body.model_dump(exclude_unset=True, exclude_none=True)
    details = {}
    if "name" in data:
        details["name"] = {"old": user.name, "new": data["name"]}
        user.name = data["name"]
    if "is_active" in data:
        details["is_active"] = {"old": user.is_active, "new": data["is_active"]}
        user.is_active = data["is_active"]
    if "password" in data:
        details["password"] = "changed"
        user.password_hash = hash_password(data["password"])
    if details:
        if "password" in data or data.get("is_active") is False:
            await revoke_all(session, user.id)
        await audit.log(
            session,
            actor_id=admin.id,
            action="user.update",
            target_type="user",
            target_id=user.id,
            details=details,
        )
    await session.commit()
    await session.refresh(user)
    return UserOut.model_validate(user)


@router.post("/users/{user_id}/reset-password", response_model=TempPasswordOut)
async def reset_user_password(user_id: uuid.UUID, admin: SuperAdmin, session: Session):
    """Any staff or rider. The temporary password is shown once."""
    user = await session.get(User, user_id, with_for_update=True)
    if user is None:
        raise not_found("User not found")
    temp = await reset_password(session, user)
    await audit.log(
        session,
        actor_id=admin.id,
        action="user.password_reset",
        target_type="user",
        target_id=user.id,
    )
    await session.commit()
    return TempPasswordOut(temp_password=temp)
