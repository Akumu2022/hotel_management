"""Rider wallet: what the rider sees. Reads the payments module; knows order codes and hotel
names, which the module itself never does."""

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from app import payments
from app.api.deps import Session
from app.api.v1.riders import Rider
from app.models import Hotel, Order, RiderProfile
from app.payments import ledger
from app.payments.config import get_payments_config

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
        "can_withdraw": False,  # B2C payouts are not switched on yet
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
