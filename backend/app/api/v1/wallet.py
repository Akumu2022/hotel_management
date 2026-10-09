"""Rider wallet: what the rider sees. Reads the payments module; knows order codes and hotel
names, which the module itself never does."""

import uuid

from fastapi import APIRouter, Header
from pydantic import Field
from sqlalchemy import select

from app import payments
from app.api.deps import HotelAdmin, Session
from app.api.v1.riders import Rider
from app.core.errors import AppError
from app.core.security import verify_password
from app.core.time import utcnow
from app.models import Hotel, Order, RiderProfile, User
from app.payments import ledger, payouts
from app.schemas.catalogue import Input
from app.payments.config import get_payments_config
from app.payments.models import HotelSettlement

router = APIRouter(prefix="/rider/wallet", tags=["wallet"])

MIN_PAYOUT = 50
PAYOUT_TIME = "9:30 pm"


@router.get("")
async def wallet(user: Rider, session: Session):
    cfg = get_payments_config()
    if not cfg.payments_enabled:
        return {"enabled": False}
    bal = await payments.get_balance(session, user.id)
    rows = await ledger.credits(session, user.id, shadow=cfg.payments_shadow)
    ids = []
    for r in rows:
        try:
            ids.append(uuid.UUID(r.order_ref or ""))
        except ValueError:
            pass
    info = {}
    if ids:
        q = select(Order.id, Order.code, Hotel.name).join(Hotel, Hotel.id == Order.hotel_id)
        for oid, code, hotel in (await session.execute(q.where(Order.id.in_(ids)))).all():
            info[str(oid)] = (code, hotel)
    number = await session.scalar(
        select(RiderProfile.mpesa_number).where(RiderProfile.user_id == user.id)
    )
    return {
        "enabled": True,
        "practice": cfg.payments_shadow,  # shadow mode: nothing real is paid yet
        "available": bal["available"],
        "pending": bal["pending"],
        "paid": bal["paid"],
        "min_payout": MIN_PAYOUT,
        "payout_time": PAYOUT_TIME,
        "mpesa_last4": (number or "")[-4:],
        "can_withdraw": True,
        "extra_charge": cfg.payout_extra_charge,
        "activity": [
            {
                "id": str(r.id),
                "amount": r.amount,
                "code": info.get(r.order_ref or "", (None, None))[0],
                "hotel": info.get(r.order_ref or "", (None, None))[1],
                "at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


class WithdrawIn(Input):
    password: str = Field(min_length=1, max_length=200)  # re-entered every time (spec 12.3)
    accept_charge: bool = False


@router.post("/withdraw")
async def withdraw(
    body: WithdrawIn,
    user: Rider,
    session: Session,
    idempotency_key: str = Header(default="", alias="Idempotency-Key"),
):
    cfg = get_payments_config()
    if not cfg.payments_enabled:
        raise AppError(404, "not_found", "Not found")
    if not 8 <= len(idempotency_key) <= 80:
        raise AppError(400, "idempotency_key_required", "Missing or invalid Idempotency-Key")
    row = await session.get(User, user.id)
    if not verify_password(row.password_hash, body.password):
        raise AppError(403, "wrong_password", "That password is not right.")
    profile = await session.scalar(select(RiderProfile).where(RiderProfile.user_id == user.id))
    if profile is None or profile.kyc_status != "approved":
        raise AppError(403, "not_approved", "Your account cannot withdraw right now.")
    try:
        p = await payouts.request_withdrawal(
            session,
            user.id,
            phone=profile.mpesa_number,
            idem_key=f"{user.id}:{idempotency_key}"[:80],
            accept_charge=body.accept_charge,
            now=utcnow(),
        )
    except payouts.PayoutError as e:
        raise AppError(409 if e.code == "charge_needed" else 422, e.code, e.message, e.extra) from e
    await session.commit()
    return {"status": p.status, "amount": p.amount, "charge": p.charge}


hotel = APIRouter(prefix="/hotel/settlements", tags=["wallet"])


@hotel.get("")
async def hotel_settlements(user: HotelAdmin, session: Session):
    """The hotel's daily payouts, each with the orders it is made of."""
    cfg = get_payments_config()
    if not cfg.payments_enabled:
        return {"enabled": False}
    rows = (
        await session.scalars(
            select(HotelSettlement)
            .where(HotelSettlement.hotel_id == user.hotel_id)
            .order_by(HotelSettlement.statement_date.desc(), HotelSettlement.created_at.desc())
            .limit(60)
        )
    ).all()
    refs = {i["order_ref"] for r in rows for i in r.detail or []}
    ids = []
    for ref in refs:
        try:
            ids.append(uuid.UUID(ref))
        except ValueError:
            pass
    codes = {}
    if ids:
        q = select(Order.id, Order.code).where(Order.id.in_(ids), Order.hotel_id == user.hotel_id)
        codes = {str(i): c for i, c in (await session.execute(q)).all()}
    shadow = cfg.payments_shadow
    return {
        "enabled": True,
        "practice": shadow,
        "coming": await ledger.balance(session, "hotel", user.hotel_id, "pending", shadow=shadow),
        "ready": await ledger.balance(session, "hotel", user.hotel_id, "available", shadow=shadow),
        "settlements": [
            {
                "id": str(r.id),
                "date": r.statement_date.isoformat(),
                "amount": r.amount,
                "status": r.status,
                "to": r.destination[-4:],
                "channel": r.channel,
                "code": r.transaction_id,
                "orders": [
                    {"code": codes.get(i["order_ref"]), "amount": i["amount"]}
                    for i in r.detail or []
                ],
            }
            for r in rows
        ],
    }
