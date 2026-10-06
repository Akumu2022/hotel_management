"""Weekly statements and payments to the platform."""

import uuid

from fastapi import APIRouter

from app.api.deps import HotelAdmin, Session, SuperAdmin
from app.api.v1.riders import Rider
from app.core.errors import not_found
from app.core.time import utcnow
from app.models import Hotel
from app.schemas.billing import ConfirmIn, PayoutIn, RejectIn, SettlementIn
from app.services import audit, billing

hotel = APIRouter(prefix="/hotel/billing", tags=["billing"])
admin = APIRouter(prefix="/admin/billing", tags=["billing"])
rider = APIRouter(prefix="/rider/earnings", tags=["billing"])


# --- Hotel admin -------------------------------------------------------------------------------


@hotel.get("")
async def hotel_billing(user: HotelAdmin, session: Session):
    h = await session.get(Hotel, user.hotel_id)
    return await billing.hotel_view(session, h, utcnow())


@hotel.post("/payments", status_code=201)
async def claim_payment(body: SettlementIn, user: HotelAdmin, session: Session):
    s = await billing.claim(
        session, user.hotel_id, code=body.mpesa_code, amount=body.amount, user_id=user.id
    )
    await session.commit()
    return billing.settlement_out(s)


# --- Super admin -------------------------------------------------------------------------------


@admin.get("")
async def overview(_: SuperAdmin, session: Session):
    return await billing.admin_overview(session, utcnow())


@admin.get("/pending/count")
async def pending_count(_: SuperAdmin, session: Session):
    return {"pending": await billing.pending_count(session)}


@admin.get("/hotels/{hotel_id}")
async def hotel_detail(hotel_id: uuid.UUID, _: SuperAdmin, session: Session):
    h = await session.get(Hotel, hotel_id)
    if h is None:
        raise not_found("Hotel not found")
    return await billing.hotel_view(session, h, utcnow())


@admin.post("/payments/{settlement_id}/confirm")
async def confirm_payment(
    settlement_id: uuid.UUID, body: ConfirmIn, user: SuperAdmin, session: Session
):
    s = await billing.confirm(session, settlement_id, user.id, utcnow(), amount=body.amount)
    await audit.log(
        session,
        actor_id=user.id,
        action="settlement.confirm",
        target_type="settlement",
        target_id=s.id,
        details={"amount": s.amount, "mpesa_code": s.mpesa_code},
    )
    await session.commit()
    return billing.settlement_out(s)


@admin.post("/payments/{settlement_id}/reject")
async def reject_payment(
    settlement_id: uuid.UUID, body: RejectIn, user: SuperAdmin, session: Session
):
    s = await billing.reject(session, settlement_id, body.note, user.id)
    await audit.log(
        session,
        actor_id=user.id,
        action="settlement.reject",
        target_type="settlement",
        target_id=s.id,
        details={"note": s.note},
    )
    await session.commit()
    return billing.settlement_out(s)


@admin.post("/run")
async def run_now(_: SuperAdmin, session: Session):
    """Make last week's statements now and apply pauses (the job does this every minute)."""
    changed = await billing.weekly_job(session, utcnow())
    await session.commit()
    return {"changed": changed}


@admin.get("/riders")
async def riders(_: SuperAdmin, session: Session):
    return await billing.riders_overview(session)


@admin.get("/riders/{rider_id}")
async def rider_detail(rider_id: uuid.UUID, _: SuperAdmin, session: Session):
    return await billing.rider_view(session, rider_id)


@admin.post("/riders/{rider_id}/payouts", status_code=201)
async def pay_rider(rider_id: uuid.UUID, body: PayoutIn, user: SuperAdmin, session: Session):
    p = await billing.pay_rider(
        session, rider_id, amount=body.amount, code=body.mpesa_code, admin_id=user.id, now=utcnow()
    )
    await audit.log(
        session,
        actor_id=user.id,
        action="rider.payout",
        target_type="user",
        target_id=rider_id,
        details={"amount": p.amount, "mpesa_code": p.mpesa_code},
    )
    await session.commit()
    return billing.payout_out(p)


# --- Rider -------------------------------------------------------------------------------------


@rider.get("")
async def my_earnings(user: Rider, session: Session):
    return await billing.rider_view(session, user.id)
