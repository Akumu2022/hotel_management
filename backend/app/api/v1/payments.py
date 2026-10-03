"""M4 payments: customer code entry, hotel confirmation / review / cash / refunds, admin tools."""

import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import exists, func, or_, select

from app.api.deps import HotelAdmin, HotelStaff, Session, SuperAdmin, get_scoped, scoped_select
from app.core.errors import AppError, not_found
from app.core.ratelimit import limit
from app.core.time import utcnow
from app.models import Hotel, Order, OrderItem, Payment, Refund, ReviewItem, RiderProfile, User
from app.schemas.payments import (
    CodeIn,
    ConfirmIn,
    HotelOrderOut,
    OutcomeOut,
    RefundIn,
    RefundOut,
    RefundSentIn,
    ResolveIn,
    ReviewOut,
    TestPaymentIn,
    TestSmsIn,
)
from app.services import ledger, media, payments, sms_parser

customer = APIRouter(tags=["payments"])
hotel = APIRouter(prefix="/hotel", tags=["hotel payments"])
admin = APIRouter(prefix="/admin", tags=["admin payments"])


def _outcome(o: payments.Outcome) -> OutcomeOut:
    return OutcomeOut(result=o.result, order_status=o.order_status, message=o.message)


# --- Customer -----------------------------------------------------------------------------------


@customer.post(
    "/track/{token}/payment-code",
    response_model=OutcomeOut,
    dependencies=[Depends(limit("payment_code", 10))],
)
async def submit_code(token: str, body: CodeIn, session: Session):
    order = (
        await session.execute(select(Order).where(Order.tracking_token == token))
    ).scalar_one_or_none()
    if order is None:
        raise not_found("Order not found")
    outcome = await payments.submit_customer_code(session, order.id, body.code, utcnow())
    await session.commit()
    return _outcome(outcome)


# --- Hotel ------------------------------------------------------------------------------------


async def _orders_out(session, orders: list[Order]) -> list[HotelOrderOut]:
    ids = [o.id for o in orders]
    rider_ids = {o.rider_id for o in orders if o.rider_id}
    riders_by_id = {}
    if rider_ids:
        rows = await session.execute(
            select(User, RiderProfile)
            .join(RiderProfile, RiderProfile.user_id == User.id)
            .where(User.id.in_(rider_ids))
        )
        riders_by_id = {u.id: (u, p) for u, p in rows.all()}
    storage = media.get_storage()
    items: dict[uuid.UUID, list[str]] = {i: [] for i in ids}
    if ids:
        for oi in (
            await session.execute(select(OrderItem).where(OrderItem.order_id.in_(ids)))
        ).scalars():
            items[oi.order_id].append(f"{oi.quantity}× {oi.name_snapshot}")
    return [
        HotelOrderOut(
            id=o.id,
            code=o.code,
            platform_bonus=o.platform_bonus,
            status=o.status,
            type=o.type,
            payment_method=o.payment_method,
            rider_fee_mode=o.rider_fee_mode,
            customer_name=o.customer_name,
            customer_phone=o.customer_phone,
            till_amount=o.till_amount,
            rider_fee=o.rider_fee,
            distance_km=o.distance_km,
            customer_trans_code=o.customer_trans_code,
            items=items[o.id],
            created_at=o.created_at,
            expires_at=o.expires_at,
            paid_at=o.paid_at,
            accepted_at=o.accepted_at,
            ready_at=o.ready_at,
            prep_minutes=o.prep_minutes,
            landmark=o.landmark,
            reason=o.reason,
            **_rider_fields(o, riders_by_id.get(o.rider_id), storage),
        )
        for o in orders
    ]


def _rider_fields(o: Order, rider, storage) -> dict:
    if rider is None:
        return {}
    user, profile = rider
    return {
        "rider_name": user.name.split(" ")[0],
        "rider_phone": user.phone,
        "rider_photo_url": storage.url(profile.photo_key) if profile.photo_key else None,
        "fee_with_food": o.rider_fee_mode == "included" and profile.payout_mode == "instant",
        "fee_handed": o.fee_hotel_confirmed_at is not None,
    }


@hotel.get("/payments/pending", response_model=list[HotelOrderOut])
async def pending_payments(user: HotelStaff, session: Session):
    """Orders waiting for the cashier: M-Pesa awaiting/checking, and unpaid cash pickups."""
    stmt = (
        scoped_select(Order, user.hotel_id)
        .where(
            # A payment already linked means it's in review, not waiting for the cashier.
            (
                Order.status.in_(payments.PENDING)
                & (Order.payment_method == "mpesa")
                & ~exists().where(Payment.order_id == Order.id)
            )
            | (
                (Order.payment_method == "cash")
                & Order.paid_at.is_(None)
                & Order.status.not_in(("cancelled", "rejected", "expired"))
            )
        )
        .order_by(Order.created_at.desc())
        .limit(100)
    )
    return await _orders_out(session, list((await session.execute(stmt)).scalars().all()))


@hotel.post("/orders/{order_id}/confirm-payment", response_model=OutcomeOut)
async def confirm_payment(order_id: uuid.UUID, body: ConfirmIn, user: HotelStaff, session: Session):
    await get_scoped(session, Order, order_id, user.hotel_id)
    outcome = await payments.confirm_manual(
        session,
        order_id,
        code=body.code,
        amount=body.amount,
        paid_at=body.paid_at,
        cashier_id=user.id,
        now=utcnow(),
    )
    await session.commit()
    return _outcome(outcome)


@hotel.post("/orders/{order_id}/cash-received", response_model=OutcomeOut)
async def cash_received(order_id: uuid.UUID, user: HotelStaff, session: Session):
    await get_scoped(session, Order, order_id, user.hotel_id)
    order = await payments.cash_received(session, order_id, user.id, utcnow())
    await session.commit()
    return OutcomeOut(result="paid", order_status=order.status, message="Cash recorded")


async def _reviews_out(session, items: list[ReviewItem]) -> list[ReviewOut]:
    out = []
    for it in items:
        order = await session.get(Order, it.order_id) if it.order_id else None
        payment = await session.get(Payment, it.payment_id) if it.payment_id else None
        hotel_row = await session.get(Hotel, it.hotel_id) if it.hotel_id else None
        out.append(
            ReviewOut(
                id=it.id,
                type=it.type,
                status=it.status,
                reason=it.reason,
                order_id=it.order_id,
                order_code=order.code if order else None,
                hotel_name=hotel_row.name if hotel_row else None,
                hotel_phone=hotel_row.phone if hotel_row else None,
                amount=payment.amount if payment else None,
                trans_code=payment.trans_code
                if payment
                else (order.customer_trans_code if order else None),
                order_total=order.till_amount if order else None,
                actions=list(payments.RESOLUTIONS.get(it.type, ("dismiss",)))
                if it.status == "open"
                else [],
                resolution=it.resolution,
                created_at=it.created_at,
                resolved_at=it.resolved_at,
            )
        )
    return out


@hotel.get("/review-items", response_model=list[ReviewOut])
async def hotel_reviews(user: HotelStaff, session: Session, status: str = "open"):
    stmt = scoped_select(ReviewItem, user.hotel_id).where(
        ReviewItem.status == status, ReviewItem.type.not_in(payments.ADMIN_TYPES)
    )
    stmt = stmt.order_by(ReviewItem.created_at.desc()).limit(100)
    return await _reviews_out(session, list((await session.execute(stmt)).scalars().all()))


@hotel.post("/review-items/{item_id}/resolve", response_model=ReviewOut)
async def hotel_resolve(item_id: uuid.UUID, body: ResolveIn, user: HotelStaff, session: Session):
    item = await get_scoped(session, ReviewItem, item_id, user.hotel_id)
    if item.type in payments.ADMIN_TYPES:
        raise not_found("Review item not found")
    # Money going back to a customer is a hotel-admin decision; cashiers confirm and accept.
    if body.action.startswith("refund") and user.role != "hotel_admin":
        raise AppError(403, "forbidden", "Only the hotel admin can approve refunds")
    item = await payments.resolve(
        session, item, body.action, user.id, utcnow(), order_code=body.order_code
    )
    await session.commit()
    return (await _reviews_out(session, [item]))[0]


async def _refunds_out(session, refunds: list[Refund]) -> list[RefundOut]:
    out = []
    for r in refunds:
        order = await session.get(Order, r.order_id)
        out.append(
            RefundOut(
                id=r.id,
                order_id=r.order_id,
                order_code=order.code,
                customer_phone=order.customer_phone,
                amount=r.amount,
                reason=r.reason,
                status=r.status,
                mpesa_code=r.mpesa_code,
                created_at=r.created_at,
                sent_at=r.sent_at,
            )
        )
    return out


@hotel.get("/refunds", response_model=list[RefundOut])
async def list_refunds(user: HotelStaff, session: Session, status: str = "approved"):
    stmt = (
        select(Refund)
        .join(Order, Order.id == Refund.order_id)
        .where(Order.hotel_id == user.hotel_id, Refund.status == status)
        .order_by(Refund.created_at.desc())
        .limit(100)
    )
    return await _refunds_out(session, list((await session.execute(stmt)).scalars().all()))


@hotel.post("/refunds", response_model=RefundOut, status_code=201)
async def approve_refund(body: RefundIn, user: HotelAdmin, session: Session):
    await get_scoped(session, Order, body.order_id, user.hotel_id)
    refund = await ledger.approve_refund(
        session,
        body.order_id,
        food=body.food,
        service_fee=body.service_fee,
        rider_fee=body.rider_fee,
        reason=body.reason,
        approved_by=user.id,
        refund_id=body.refund_id,
    )
    await session.commit()
    return (await _refunds_out(session, [refund]))[0]


@hotel.post("/refunds/{refund_id}/sent", response_model=RefundOut)
async def refund_sent(refund_id: uuid.UUID, body: RefundSentIn, user: HotelStaff, session: Session):
    refund = await session.get(Refund, refund_id)
    order = await session.get(Order, refund.order_id) if refund else None
    if order is None or order.hotel_id != user.hotel_id:
        raise not_found("Refund not found")
    code = payments.normalize_code(body.mpesa_code)
    refund = await ledger.mark_refund_sent(session, refund_id, mpesa_code=code, sent_by=user.id)
    await session.commit()
    return (await _refunds_out(session, [refund]))[0]


# --- Admin ------------------------------------------------------------------------------------


# Payment review belongs to each hotel (DECISIONS D19). The super admin sees only what needs
# the duty person: items with no hotel (an unreadable SMS, an unknown Till) and hotel items
# left open longer than ESCALATE_AFTER (D5), to chase by phone.
ESCALATE_AFTER = timedelta(minutes=15)


def _needs_attention(now: datetime):
    return or_(
        ReviewItem.hotel_id.is_(None),
        ReviewItem.type.in_(payments.ADMIN_TYPES),
        ReviewItem.created_at < now - ESCALATE_AFTER,
    )


@admin.get("/review-items", response_model=list[ReviewOut])
async def admin_reviews(
    _: SuperAdmin, session: Session, view: Literal["attention", "all"] = "attention"
):
    stmt = select(ReviewItem).where(ReviewItem.status == "open")
    if view == "attention":
        stmt = stmt.where(_needs_attention(utcnow()))
    stmt = stmt.order_by(ReviewItem.created_at).limit(200)
    return await _reviews_out(session, list((await session.execute(stmt)).scalars().all()))


@admin.post("/review-items/{item_id}/resolve", response_model=ReviewOut)
async def admin_resolve(item_id: uuid.UUID, body: ResolveIn, user: SuperAdmin, session: Session):
    item = await session.get(ReviewItem, item_id)
    if item is None:
        raise not_found("Review item not found")
    if item.hotel_id is not None and item.type not in payments.ADMIN_TYPES:
        raise AppError(403, "hotel_item", "The hotel resolves its own payments. Call them.")
    item = await payments.resolve(
        session, item, body.action, user.id, utcnow(), order_code=body.order_code
    )
    await session.commit()
    return (await _reviews_out(session, [item]))[0]


@admin.get("/review-items/count")
async def admin_review_count(_: SuperAdmin, session: Session):
    n = await session.scalar(
        select(func.count())
        .select_from(ReviewItem)
        .where(ReviewItem.status == "open", _needs_attention(utcnow()))
    )
    return {"open": n}


@admin.post("/test-payment")
async def test_payment(body: TestPaymentIn, _: SuperAdmin, session: Session):
    """Simulate an M-Pesa message on a Till, as the M8 forwarder will send. For testing the
    matching rules before the SMS app exists."""
    now = utcnow()
    if body.kind == "reversal":
        payment = await payments.record_reversal(session, body.code, now)
        await session.commit()
        return {"stored": payment is not None, "result": "reversal" if payment else "unknown_code"}
    payment, outcome = await payments.record_incoming(
        session,
        till_number=body.till_number,
        code=body.code,
        amount=body.amount,
        paid_at=body.paid_at or now,
        source="manual",
        phone_digits=body.phone_digits,
        now=now,
    )
    await session.commit()
    return {
        "stored": True,
        "matched_order": str(payment.order_id) if payment.order_id else None,
        "result": outcome.result if outcome else "unmatched",
        "message": outcome.message if outcome else "No order matched; it is in the review queue.",
    }


@admin.post("/test-sms")
async def test_sms(body: TestSmsIn, _: SuperAdmin, session: Session):
    """Parse a pasted Till SMS and run it through matching, as the M8 SMS app will."""
    now = utcnow()
    parsed = sms_parser.parse(body.raw_text)
    out = {
        "parse_status": parsed.status,
        "code": parsed.code,
        "amount": parsed.amount,
        "paid_at": parsed.paid_at,
        "phone": parsed.phone_digits,
        "name": parsed.sender_name,
    }
    if parsed.status == "reversal":
        payment = await payments.record_reversal(session, parsed.code, now)
        out["result"] = "reversal" if payment else "unknown_code"
    elif parsed.status == "parsed":
        payment, outcome = await payments.record_incoming(
            session,
            till_number=body.till_number,
            code=parsed.code,
            amount=parsed.amount,
            paid_at=parsed.paid_at,
            source="manual",
            phone_digits=parsed.phone_digits,
            now=now,
        )
        out["result"] = outcome.result if outcome else "unmatched"
        out["message"] = (
            outcome.message if outcome else "No order matched; it is in the review queue."
        )
    else:
        hotel_id = await session.scalar(
            select(Hotel.id).where(Hotel.till_number == body.till_number)
        )
        await payments.open_review(
            session,
            type="parse_failed",
            hotel_id=hotel_id,
            reason=f"Unreadable SMS ({parsed.reason}): {body.raw_text[:200]}",
        )
        out["result"] = "parse_failed"
        out["message"] = parsed.reason
    await session.commit()
    return out
