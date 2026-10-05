"""Riders (DECISIONS D21): sign-up and KYC review, delivery jobs, the admin dispatch board."""

import uuid
from datetime import datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import Response, StreamingResponse
from pydantic import Field, ValidationError
from sqlalchemy import and_, or_, select

from app.api.deps import CurrentUser, Session, SuperAdmin, require_roles
from app.api.v1.auth import _out as token_out
from app.api.v1.orders_board import SSE_HEADERS
from app.core.errors import AppError
from app.core.ratelimit import limit
from app.core.time import utcnow
from app.models import Hotel, Order, OrderItem, RiderProfile, User
from app.schemas.auth import TokenOut
from app.schemas.catalogue import Input
from app.schemas.common import Schema
from app.schemas.riders import ReviewIn, RiderDetailsIn, RiderOut, RiderRegisterIn, SubmitIn
from app.services import auth, delivery, events, media, ratings, riders, tracking
from app.services.media import Storage

public = APIRouter(tags=["riders"])
rider = APIRouter(prefix="/rider", tags=["riders"])
admin = APIRouter(prefix="/admin/riders", tags=["riders"])

Rider = Annotated[CurrentUser, Depends(require_roles("rider"))]
StorageDep = Annotated[Storage, Depends(media.get_storage)]
PrivateDep = Annotated[riders.PrivateStorage, Depends(riders.get_private_storage)]


async def _out(session, p: RiderProfile, storage: Storage) -> RiderOut:
    user = await session.get(User, p.user_id)
    reviewer = await session.get(User, p.reviewed_by) if p.reviewed_by else None
    return RiderOut(
        id=user.id,
        name=user.name,
        phone=user.phone,
        national_id=p.national_id,
        next_of_kin=p.next_of_kin,
        next_of_kin_phone=p.next_of_kin_phone,
        residence_area=p.residence_area,
        photos={k: getattr(p, f"{k}_key") is not None for k in riders.KINDS},
        photo_url=storage.url(p.photo_key) if p.photo_key else None,
        kyc_status=p.kyc_status,
        kyc_note=p.kyc_note,
        submitted_at=p.submitted_at,
        reviewed_at=p.reviewed_at,
        reviewed_by_name=reviewer.name if reviewer else None,
        is_online=p.is_online,
        created_at=user.created_at,
    )


# --- Public: sign up --------------------------------------------------------------------------


@public.post(
    "/riders/apply",
    response_model=TokenOut,
    status_code=201,
    dependencies=[Depends(limit("rider_apply", 5))],
)
async def apply(
    session: Session,
    storage: StorageDep,
    private: PrivateDep,
    name: Annotated[str, Form()],
    phone: Annotated[str, Form()],
    password: Annotated[str, Form()],
    national_id: Annotated[str, Form()],
    next_of_kin: Annotated[str, Form()],
    next_of_kin_phone: Annotated[str, Form()],
    residence_area: Annotated[str, Form()],
    consent: Annotated[bool, Form()],
    id_front: Annotated[UploadFile, File()],
    id_back: Annotated[UploadFile, File()],
    selfie: Annotated[UploadFile, File()],
):
    """The whole rider application in one go: details, ID front and back, selfie, consent.
    Creates the account as "pending" (waiting for the Chakula team) and logs the rider in."""
    try:
        body = RiderRegisterIn(
            name=name,
            phone=phone,
            password=password,
            national_id=national_id,
            next_of_kin=next_of_kin,
            next_of_kin_phone=next_of_kin_phone,
            residence_area=residence_area,
        )
    except ValidationError as e:
        raise RequestValidationError(
            [{**err, "loc": ("body", *err["loc"])} for err in e.errors()]
        ) from None
    photos = {
        kind: await f.read(media.MAX_UPLOAD_BYTES + 1)
        for kind, f in (("id_front", id_front), ("id_back", id_back), ("selfie", selfie))
    }
    await riders.apply(
        session, private, storage, photos=photos, consent=consent, now=utcnow(), **body.model_dump()
    )
    pair = await auth.login(session, body.phone, body.password)
    await session.commit()
    return token_out(pair)


# --- Rider: own application -------------------------------------------------------------------


@rider.get("/me", response_model=RiderOut)
async def me(user: Rider, session: Session, storage: StorageDep):
    return await _out(session, await riders.profile(session, user.id), storage)


@rider.patch("/me", response_model=RiderOut)
async def edit_me(body: RiderDetailsIn, user: Rider, session: Session, storage: StorageDep):
    row = await session.get(User, user.id)
    p = await riders.update_details(session, row, body.model_dump(exclude_unset=True))
    await session.commit()
    return await _out(session, p, storage)


@rider.post("/kyc/{kind}", response_model=RiderOut)
async def upload_kyc(
    kind: Literal["id_front", "id_back", "selfie"],
    user: Rider,
    session: Session,
    storage: StorageDep,
    private: PrivateDep,
    file: Annotated[UploadFile, File()],
):
    p = await riders.profile(session, user.id, lock=True)
    riders.save_photo(private, storage, p, kind, await file.read(media.MAX_UPLOAD_BYTES + 1))
    await session.commit()
    return await _out(session, p, storage)


@rider.post("/submit", response_model=RiderOut)
async def submit(body: SubmitIn, user: Rider, session: Session, storage: StorageDep):
    p = await riders.submit(session, user.id, consent=body.consent, now=utcnow())
    await session.commit()
    return await _out(session, p, storage)


# --- Super admin: review ----------------------------------------------------------------------


@admin.get("", response_model=list[RiderOut])
async def list_riders(
    _: SuperAdmin,
    session: Session,
    storage: StorageDep,
    status: Literal["pending", "approved", "rejected", "suspended", "draft", "all"] = "all",
):
    stmt = select(RiderProfile).join(User, User.id == RiderProfile.user_id)
    if status != "all":
        stmt = stmt.where(RiderProfile.kyc_status == status)
    stmt = stmt.order_by(RiderProfile.submitted_at.desc().nulls_last(), User.created_at.desc())
    out = [await _out(session, p, storage) for p in (await session.execute(stmt)).scalars()]
    stars = await ratings.rider_stars(session, [r.id for r in out])
    for r in out:
        r.rating, r.rating_count = stars[r.id].average, stars[r.id].count
    return out


@admin.get("/{rider_id}", response_model=RiderOut)
async def get_rider(rider_id: uuid.UUID, _: SuperAdmin, session: Session, storage: StorageDep):
    return await _out(session, await riders.profile(session, rider_id), storage)


@admin.get("/{rider_id}/kyc/{kind}")
async def kyc_photo(
    rider_id: uuid.UUID,
    kind: Literal["id_front", "id_back", "selfie"],
    _: SuperAdmin,
    session: Session,
    private: PrivateDep,
):
    """The only way to see an ID photo or selfie: super admins, never cached."""
    p = await riders.profile(session, rider_id)
    key = getattr(p, f"{kind}_key")
    if key is None:
        raise AppError(404, "not_found", "No photo uploaded")
    return Response(
        private.get(key),
        media_type="image/webp",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@admin.post("/{rider_id}/review", response_model=RiderOut)
async def review(
    rider_id: uuid.UUID,
    body: ReviewIn,
    admin_user: SuperAdmin,
    session: Session,
    storage: StorageDep,
):
    p = await riders.review(session, rider_id, body.action, body.note, admin_user.id, utcnow())
    await session.commit()
    return await _out(session, p, storage)


# --- Deliveries (rider) -----------------------------------------------------------------------
# Open jobs show no customer details; the customer's name, phone and pin appear once the job is
# the rider's. The delivery code is never sent to riders: the customer reads it out.


class OnlineIn(Input):
    online: bool


class LocationIn(Input):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: int | None = Field(None, ge=0, le=100_000)


class PickupIn(Input):
    fee_received: bool | None = None  # option A instant: did the fee come with the food?


class DeliverIn(Input):
    code: str = Field(pattern=r"^\d{4}$")
    cash_fee_received: bool | None = None  # option B


class FailIn(Input):
    reason: Literal[
        "customer_unreachable", "customer_refused", "wrong_location", "accident", "other"
    ]
    note: str | None = Field(None, max_length=200)


FAIL_TEXT = {
    "customer_unreachable": "Customer unreachable at the pin",
    "customer_refused": "Customer refused the order",
    "wrong_location": "Wrong or unreachable location",
    "accident": "Accident or food damaged on the way",
    "other": "Other",
}


class JobOut(Schema):
    id: uuid.UUID
    code: str
    status: str
    hotel_name: str
    hotel_phone: str
    hotel_lat: float | None
    hotel_lng: float | None
    distance_km: float | None
    rider_fee: int
    collect_cash_fee: bool  # option B: collect the fee from the customer
    fee_with_food: bool  # option A instant: the hotel hands the fee over at pickup
    items: list[str]
    prep_minutes: int | None
    accepted_at: datetime | None
    ready_at: datetime | None
    closed_at: datetime | None = None
    mine: bool
    # Only for the assigned rider:
    customer_name: str | None = None
    customer_phone: str | None = None
    lat: float | None = None
    lng: float | None = None
    landmark: str | None = None
    seen: bool = True
    fee_rider_confirmed: bool = False
    fee_not_paid: bool = False
    code_attempts_left: int | None = None


async def _jobs_out(session, orders: list[Order], rider_id: uuid.UUID) -> list[JobOut]:
    if not orders:
        return []
    ids = [o.id for o in orders]
    hotel_ids = {o.hotel_id for o in orders}
    hotels = {
        h.id: h
        for h in (await session.execute(select(Hotel).where(Hotel.id.in_(hotel_ids)))).scalars()
    }
    items: dict = {}
    rows = await session.execute(
        select(OrderItem.order_id, OrderItem.name_snapshot, OrderItem.quantity).where(
            OrderItem.order_id.in_(ids)
        )
    )
    for oid, name, qty in rows.all():
        items.setdefault(oid, []).append(f"{qty}× {name}")
    mode = (await riders.profile(session, rider_id)).payout_mode
    out = []
    for o in orders:
        h = hotels[o.hotel_id]
        mine = o.rider_id == rider_id
        private = (
            {
                "customer_name": o.customer_name,
                "customer_phone": o.customer_phone,
                "lat": o.lat,
                "lng": o.lng,
                "landmark": o.landmark,
                "seen": o.rider_seen_at is not None,
                "fee_rider_confirmed": o.fee_rider_confirmed_at is not None,
                "fee_not_paid": o.fee_not_paid_at is not None,
                "code_attempts_left": delivery.MAX_CODE_ATTEMPTS - o.delivery_code_attempts,
            }
            if mine
            else {}
        )
        out.append(
            JobOut(
                id=o.id,
                code=o.code,
                status=o.status,
                hotel_name=h.name,
                hotel_phone=h.phone,
                hotel_lat=h.lat,
                hotel_lng=h.lng,
                distance_km=o.distance_km,
                rider_fee=o.rider_fee,
                collect_cash_fee=o.rider_fee_mode == "cash",
                fee_with_food=o.rider_fee_mode == "included" and mode == "instant",
                items=items.get(o.id, []),
                prep_minutes=o.prep_minutes,
                accepted_at=o.accepted_at,
                ready_at=o.ready_at,
                closed_at=o.closed_at,
                mine=mine,
                **private,
            )
        )
    return out


async def _job(session, order: Order, user_id) -> JobOut:
    await session.commit()
    return (await _jobs_out(session, [order], user_id))[0]


@rider.post("/location", status_code=204)
async def location(body: LocationIn, user: Rider, session: Session):
    """The rider's phone, every ~30 s while online (D27)."""
    await tracking.record(
        session, user.id, lat=body.lat, lng=body.lng, accuracy_m=body.accuracy_m, now=utcnow()
    )
    await session.commit()


@rider.post("/online", response_model=RiderOut)
async def go_online(body: OnlineIn, user: Rider, session: Session, storage: StorageDep):
    p = await delivery.set_online(session, user.id, body.online, utcnow())
    await session.commit()
    return await _out(session, p, storage)


@rider.get("/jobs", response_model=list[JobOut])
async def jobs(user: Rider, session: Session):
    """Open deliveries anyone can take, and this rider's own current ones."""
    await riders.require_approved(session, user.id)
    open_job = and_(Order.rider_id.is_(None), Order.status.in_(delivery.CLAIMABLE))
    my_job = and_(Order.rider_id == user.id, Order.status.in_(delivery.ON_JOB))
    stmt = (
        select(Order)
        .where(Order.type == "delivery", or_(open_job, my_job))
        .order_by(Order.accepted_at)
    )
    return await _jobs_out(session, list((await session.execute(stmt)).scalars()), user.id)


@rider.get("/jobs/history", response_model=list[JobOut])
async def job_history(user: Rider, session: Session):
    stmt = (
        select(Order)
        .where(Order.rider_id == user.id, Order.status.in_(("delivered", "failed_delivery")))
        .order_by(Order.closed_at.desc())
        .limit(50)
    )
    return await _jobs_out(session, list((await session.execute(stmt)).scalars()), user.id)


@rider.post("/jobs/{order_id}/claim", response_model=JobOut)
async def claim_job(order_id: uuid.UUID, user: Rider, session: Session):
    return await _job(session, await delivery.claim(session, order_id, user.id, utcnow()), user.id)


@rider.post("/jobs/{order_id}/seen", response_model=JobOut)
async def seen_job(order_id: uuid.UUID, user: Rider, session: Session):
    return await _job(session, await delivery.seen(session, order_id, user.id), user.id)


@rider.post("/jobs/{order_id}/release", response_model=JobOut)
async def release_job(order_id: uuid.UUID, user: Rider, session: Session):
    return await _job(session, await delivery.release(session, order_id, user.id), user.id)


@rider.post("/jobs/{order_id}/picked-up", response_model=JobOut)
async def picked_up(order_id: uuid.UUID, body: PickupIn, user: Rider, session: Session):
    order = await delivery.rider_picked_up(
        session, order_id, user.id, fee_received=body.fee_received, now=utcnow()
    )
    return await _job(session, order, user.id)


@rider.post("/jobs/{order_id}/on-the-way", response_model=JobOut)
async def on_the_way(order_id: uuid.UUID, user: Rider, session: Session):
    return await _job(
        session, await delivery.on_the_way(session, order_id, user.id, utcnow()), user.id
    )


@rider.post("/jobs/{order_id}/delivered", response_model=JobOut)
async def delivered(order_id: uuid.UUID, body: DeliverIn, user: Rider, session: Session):
    try:
        order = await delivery.delivered(
            session,
            order_id,
            user.id,
            code=body.code,
            cash_fee_received=body.cash_fee_received,
            now=utcnow(),
        )
    except AppError as e:
        if e.code == "wrong_code":
            await session.commit()  # the failed attempt counts
        raise
    return await _job(session, order, user.id)


@rider.post("/jobs/{order_id}/cash-fee-received", response_model=JobOut)
async def cash_fee(order_id: uuid.UUID, user: Rider, session: Session):
    order = await delivery.cash_fee_received(session, order_id, user.id)
    return await _job(session, order, user.id)


@rider.post("/jobs/{order_id}/fee-not-paid", response_model=JobOut)
async def fee_not_paid(order_id: uuid.UUID, user: Rider, session: Session):
    order = await delivery.fee_not_paid(session, order_id, user.id, utcnow())
    return await _job(session, order, user.id)


@rider.post("/jobs/{order_id}/failed", response_model=JobOut)
async def failed(order_id: uuid.UUID, body: FailIn, user: Rider, session: Session):
    note = body.note.strip() if body.note else ""
    reason = FAIL_TEXT[body.reason] + (f": {note}" if note else "")
    order = await delivery.report_failed(session, order_id, user.id, reason, utcnow())
    return await _job(session, order, user.id)


@rider.get("/events")
async def rider_events(user: Rider, session: Session):
    await riders.require_approved(session, user.id)
    return StreamingResponse(
        events.stream("riders"), media_type="text/event-stream", headers=SSE_HEADERS
    )


# --- Dispatch (super admin) -------------------------------------------------------------------

dispatch = APIRouter(prefix="/admin/dispatch", tags=["riders"])


class AssignIn(Input):
    rider_id: uuid.UUID


class DispatchOut(Schema):
    id: uuid.UUID
    code: str
    status: str
    hotel_name: str
    customer_name: str
    landmark: str | None
    distance_km: float | None
    rider_fee: int
    rider_fee_mode: str
    rider_id: uuid.UUID | None
    rider_name: str | None
    accepted_at: datetime | None
    ready_at: datetime | None
    assigned_at: datetime | None
    rider_seen: bool = False
    picked_up_at: datetime | None
    # For the Dispatch map (D27): where the food is and where it's going.
    hotel_lat: float | None = None
    hotel_lng: float | None = None
    lat: float | None = None
    lng: float | None = None


class RiderBrief(Schema):
    id: uuid.UUID
    name: str
    phone: str
    photo_url: str | None
    is_online: bool
    active_jobs: int
    # The rider's last finished delivery today: tells dispatch they're free again (owner, D25).
    last_code: str | None = None
    last_status: str | None = None
    last_at: datetime | None = None
    # Live location (D27); `live` is false when the last fix is over 5 minutes old.
    lat: float | None = None
    lng: float | None = None
    accuracy_m: int | None = None
    location_at: datetime | None = None
    live: bool = False


class FinishedOut(Schema):
    id: uuid.UUID
    code: str
    status: str  # delivered | failed_delivery
    hotel_name: str
    customer_name: str
    rider_id: uuid.UUID | None
    rider_name: str | None
    picked_up_at: datetime | None
    closed_at: datetime


FINISHED = ("delivered", "failed_delivery")


@dispatch.get("")
async def dispatch_board(_: SuperAdmin, session: Session, storage: StorageDep):
    now = utcnow()
    orders = (
        await session.execute(
            select(Order, Hotel)
            .join(Hotel, Hotel.id == Order.hotel_id)
            .where(Order.type == "delivery", Order.status.in_(delivery.ON_JOB))
            .order_by(Order.accepted_at)
        )
    ).all()
    rider_rows = (
        await session.execute(
            select(User, RiderProfile)
            .join(RiderProfile, RiderProfile.user_id == User.id)
            .where(RiderProfile.kyc_status == "approved")
            .order_by(RiderProfile.is_online.desc(), User.name)
        )
    ).all()
    names = {u.id: u.name for u, _ in rider_rows}
    finished = (
        await session.execute(
            select(Order, Hotel.name)
            .join(Hotel, Hotel.id == Order.hotel_id)
            .where(
                Order.type == "delivery",
                Order.status.in_(FINISHED),
                Order.closed_at >= utcnow() - timedelta(hours=12),
            )
            .order_by(Order.closed_at.desc())
            .limit(30)
        )
    ).all()
    last: dict = {}
    for o, _ in finished:  # newest first: keep the first per rider
        if o.rider_id and o.rider_id not in last:
            last[o.rider_id] = o
    active: dict = {}
    for o, _ in orders:
        if o.rider_id:
            active[o.rider_id] = active.get(o.rider_id, 0) + 1
    return {
        "orders": [
            DispatchOut(
                id=o.id,
                code=o.code,
                status=o.status,
                hotel_name=hotel.name,
                hotel_lat=hotel.lat,
                hotel_lng=hotel.lng,
                lat=o.lat,
                lng=o.lng,
                customer_name=o.customer_name,
                landmark=o.landmark,
                distance_km=o.distance_km,
                rider_fee=o.rider_fee,
                rider_fee_mode=o.rider_fee_mode,
                rider_id=o.rider_id,
                rider_name=names.get(o.rider_id),
                accepted_at=o.accepted_at,
                ready_at=o.ready_at,
                assigned_at=o.assigned_at,
                rider_seen=o.rider_seen_at is not None,
                picked_up_at=o.picked_up_at,
            )
            for o, hotel in orders
        ],
        "riders": [
            RiderBrief(
                id=u.id,
                name=u.name,
                phone=u.phone,
                photo_url=storage.url(p.photo_key) if p.photo_key else None,
                is_online=p.is_online,
                active_jobs=active.get(u.id, 0),
                last_code=last[u.id].code if u.id in last else None,
                last_status=last[u.id].status if u.id in last else None,
                last_at=last[u.id].closed_at if u.id in last else None,
                lat=p.last_lat,
                lng=p.last_lng,
                accuracy_m=p.last_accuracy_m,
                location_at=p.last_location_at,
                live=tracking.is_live(p, now),
            )
            for u, p in rider_rows
        ],
        "finished": [
            FinishedOut(
                id=o.id,
                code=o.code,
                status=o.status,
                hotel_name=hotel,
                customer_name=o.customer_name,
                rider_id=o.rider_id,
                rider_name=names.get(o.rider_id),
                picked_up_at=o.picked_up_at,
                closed_at=o.closed_at,
            )
            for o, hotel in finished
        ],
    }


@dispatch.get("/{order_id}/trail")
async def order_trail(order_id: uuid.UUID, _: SuperAdmin, session: Session):
    """Where the rider was during this job (D27)."""
    return await tracking.trail(session, order_id)


@dispatch.post("/{order_id}/assign")
async def assign(order_id: uuid.UUID, body: AssignIn, admin_user: SuperAdmin, session: Session):
    order = await delivery.assign(session, order_id, body.rider_id, admin_user.id, utcnow())
    await session.commit()
    return {"id": str(order.id), "rider_id": str(order.rider_id), "status": order.status}
