"""the hotel order board, status actions, and live updates (SSE) for hotels, customers and
the admin duty board."""

import uuid
from datetime import timedelta

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import HotelAdmin, HotelStaff, Session, SuperAdmin, scoped_select
from app.api.v1.payments import _orders_out
from app.core.errors import AppError, not_found
from app.core.time import utcnow
from app.models import Hotel, Order
from app.schemas.payments import AcceptIn, CancelIn, HotelOrderOut, RejectIn
from app.services import delivery, events, order_flow

hotel = APIRouter(prefix="/hotel", tags=["hotel orders"])
public = APIRouter(tags=["tracking"])
admin = APIRouter(prefix="/admin", tags=["admin"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


@hotel.get("/orders", response_model=list[HotelOrderOut])
async def board(user: HotelStaff, session: Session, view: str = "active"):
    """`active`: waiting for acceptance and in the kitchen. `done`: closed in the last 24 h."""
    stmt = scoped_select(Order, user.hotel_id)
    if view == "done":
        stmt = stmt.where(
            Order.status.in_(
                ("collected", "delivered", "rejected", "cancelled", "picked_up", "on_the_way")
            ),
            Order.updated_at >= utcnow() - timedelta(hours=24),
        ).order_by(Order.updated_at.desc())
    else:
        stmt = stmt.where(
            Order.status.in_(order_flow.ACTIVE)
            | ((Order.status == "awaiting_payment") & (Order.payment_method == "cash"))
        ).order_by(Order.created_at)
    return await _orders_out(
        session, list((await session.execute(stmt.limit(200))).scalars().all())
    )


async def _one(session, order: Order) -> HotelOrderOut:
    return (await _orders_out(session, [order]))[0]


@hotel.post("/orders/{order_id}/accept", response_model=HotelOrderOut)
async def accept(order_id: uuid.UUID, body: AcceptIn, user: HotelStaff, session: Session):
    order = await order_flow.accept(
        session,
        order_id,
        prep_minutes=body.prep_minutes,
        user_id=user.id,
        hotel_id=user.hotel_id,
        now=utcnow(),
    )
    await session.commit()
    return await _one(session, order)


@hotel.post("/orders/{order_id}/reject", response_model=HotelOrderOut)
async def reject(order_id: uuid.UUID, body: RejectIn, user: HotelStaff, session: Session):
    order = await order_flow.reject(
        session,
        order_id,
        reason_code=body.reason,
        note=body.note,
        user_id=user.id,
        hotel_id=user.hotel_id,
        now=utcnow(),
    )
    await session.commit()
    return await _one(session, order)


@hotel.post("/orders/{order_id}/preparing", response_model=HotelOrderOut)
async def preparing(order_id: uuid.UUID, user: HotelStaff, session: Session):
    order = await order_flow.preparing(
        session, order_id, user_id=user.id, hotel_id=user.hotel_id, now=utcnow()
    )
    await session.commit()
    return await _one(session, order)


@hotel.post("/orders/{order_id}/ready", response_model=HotelOrderOut)
async def ready(order_id: uuid.UUID, user: HotelStaff, session: Session):
    order = await order_flow.ready(
        session, order_id, user_id=user.id, hotel_id=user.hotel_id, now=utcnow()
    )
    await session.commit()
    return await _one(session, order)


@hotel.post("/orders/{order_id}/cancel", response_model=HotelOrderOut)
async def cancel(order_id: uuid.UUID, body: CancelIn, user: HotelAdmin, session: Session):
    """Cancel & refund an accepted order the hotel can't finish (hotel admin only)."""
    order = await order_flow.cancel_after_accept(
        session,
        order_id,
        reason_code=body.reason,
        note=body.note.strip() if body.note else None,
        user_id=user.id,
        hotel_id=user.hotel_id,
        now=utcnow(),
    )
    await session.commit()
    return (await _orders_out(session, [order]))[0]


@admin.get("/orders/{code}")
async def find_order(code: str, _: SuperAdmin, session: Session):
    """Look an order up by its code (support calls)."""
    order = await session.scalar(
        select(Order).where(Order.code == code.strip().lstrip("#").upper())
    )
    if order is None:
        raise AppError(404, "not_found", "No order with that number")
    out = (await _orders_out(session, [order]))[0].model_dump(mode="json")
    hotel_row = await session.get(Hotel, order.hotel_id)
    return {
        **out,
        "hotel_name": hotel_row.name,
        "hotel_phone": hotel_row.phone,
        "tracking_token": order.tracking_token,
        "can_cancel": order.status in order_flow.CANCELLABLE_AFTER_ACCEPT,
    }


@admin.post("/orders/{order_id}/cancel", response_model=HotelOrderOut)
async def admin_cancel(order_id: uuid.UUID, body: CancelIn, user: SuperAdmin, session: Session):
    order = await order_flow.cancel_after_accept(
        session,
        order_id,
        reason_code=body.reason,
        note=body.note.strip() if body.note else None,
        user_id=user.id,
        hotel_id=None,
        now=utcnow(),
        actor_type="admin",
    )
    await session.commit()
    return (await _orders_out(session, [order]))[0]


@hotel.post("/orders/{order_id}/handed-to-rider", response_model=HotelOrderOut)
async def handed_to_rider(order_id: uuid.UUID, user: HotelStaff, session: Session):
    """The rider has the food (and, for option A instant, the fee)."""
    order = await delivery.hotel_handover(
        session, order_id, hotel_id=user.hotel_id, user_id=user.id, now=utcnow()
    )
    await session.commit()
    return (await _orders_out(session, [order]))[0]


@hotel.post("/orders/{order_id}/collected", response_model=HotelOrderOut)
async def collected(order_id: uuid.UUID, user: HotelStaff, session: Session):
    order = await order_flow.collected(
        session, order_id, user_id=user.id, hotel_id=user.hotel_id, now=utcnow()
    )
    await session.commit()
    return await _one(session, order)


@hotel.get("/events")
async def hotel_events(user: HotelStaff):
    """Live order changes for this hotel. EventSource has no headers: use ?access_token=."""
    return StreamingResponse(
        events.stream(f"hotel:{user.hotel_id}"), media_type="text/event-stream", headers=SSE_HEADERS
    )


@public.get("/track/{token}/events")
async def track_events(token: str, session: Session):
    order = (
        await session.execute(select(Order.id).where(Order.tracking_token == token))
    ).scalar_one_or_none()
    if order is None:
        raise not_found("Order not found")
    return StreamingResponse(
        events.stream(f"order:{token}"), media_type="text/event-stream", headers=SSE_HEADERS
    )


@admin.get("/alerts")
async def alerts(_: SuperAdmin, session: Session):
    """Duty alerts: paid orders not accepted after the alert time."""
    return {"unaccepted": await order_flow.duty_alerts(session, utcnow())}


@admin.get("/events")
async def admin_events(_: SuperAdmin):
    return StreamingResponse(
        events.stream("admin"), media_type="text/event-stream", headers=SSE_HEADERS
    )
