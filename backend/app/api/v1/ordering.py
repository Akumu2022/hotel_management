"""Customer ordering: quotes, placement, tracking. No login; the tracking token is the access."""

import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response
from pydantic import Field
from sqlalchemy import func, select

from app.api.deps import Session
from app.core.errors import AppError, not_found
from app.core.ratelimit import limit
from app.core.time import utcnow
from app.models import (
    Hotel,
    LedgerEntry,
    Order,
    OrderEvent,
    OrderItem,
    Product,
    Refund,
    RiderProfile,
    User,
)
from app.schemas.catalogue import Input
from app.schemas.common import Schema
from app.schemas.orders import (
    OrderIn,
    OrderPlaced,
    QuoteIn,
    QuoteOut,
    TrackEvent,
    TrackItem,
    TrackOut,
)
from app.services import delivery, ledger, media, orders
from app.services.media import Storage

router = APIRouter(tags=["ordering"])

StorageDep = Annotated[Storage, Depends(media.get_storage)]

_KEY = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


@router.post("/quotes", response_model=QuoteOut, dependencies=[Depends(limit("quote", 60))])
async def quote(body: QuoteIn, session: Session):
    """Server-calculated totals for a cart. No side effects."""
    return orders.quote_out(await orders.price(session, body, utcnow()))


@router.post(
    "/orders",
    response_model=OrderPlaced,
    status_code=201,
    dependencies=[Depends(limit("order", 10))],
)
async def place_order(
    body: OrderIn,
    session: Session,
    response: Response,
    idempotency_key: Annotated[str | None, Header()] = None,
):
    if not idempotency_key or not _KEY.match(idempotency_key):
        raise AppError(400, "idempotency_key_required", "Missing or invalid Idempotency-Key")
    order, created = await orders.place(session, body, idempotency_key, utcnow())
    await session.commit()
    if not created:
        response.status_code = 200
    hotel = await session.get(Hotel, order.hotel_id)
    return OrderPlaced(
        code=order.code,
        tracking_token=order.tracking_token,
        status=order.status,
        till_number=hotel.till_number,
        till_amount=order.till_amount,
        platform_bonus=order.platform_bonus,
        bonus_kind=order.bonus_kind,
        payment_method=order.payment_method,
        expires_at=order.expires_at,
    )


async def _by_token(session, token: str) -> Order:
    if len(token) > 64:
        raise not_found("Order not found")
    order = (
        await session.execute(select(Order).where(Order.tracking_token == token))
    ).scalar_one_or_none()
    if order is None:
        raise not_found("Order not found")
    return order


@router.get("/track/{token}", response_model=TrackOut, dependencies=[Depends(limit("track", 120))])
async def track(token: str, session: Session, storage: StorageDep):
    order = await _by_token(session, token)
    hotel = await session.get(Hotel, order.hotel_id)
    items = (
        (await session.execute(select(OrderItem).where(OrderItem.order_id == order.id)))
        .scalars()
        .all()
    )
    events = (
        (
            await session.execute(
                select(OrderEvent)
                .where(OrderEvent.order_id == order.id)
                .order_by(OrderEvent.created_at)
            )
        )
        .scalars()
        .all()
    )
    rider = await session.get(User, order.rider_id) if order.rider_id else None
    thumbs = dict(
        (
            await session.execute(
                select(Product.id, Product.thumb_key).where(
                    Product.id.in_([i.product_id for i in items])
                )
            )
        ).all()
    )
    on_the_way = order.status in ("picked_up", "on_the_way", "delivered")
    profile = await session.get(RiderProfile, order.rider_id) if rider else None
    return TrackOut(
        code=order.code,
        status=order.status,
        type=order.type,
        payment_method=order.payment_method,
        rider_fee_mode=order.rider_fee_mode,
        hotel_name=hotel.name,
        hotel_slug=hotel.slug,
        hotel_phone=hotel.phone,
        till_number=hotel.till_number,
        items=[
            TrackItem(
                product_id=i.product_id,
                option_ids=[o["id"] for o in i.options_snapshot],
                name=i.name_snapshot,
                options=[o["name"] for o in i.options_snapshot],
                quantity=i.quantity,
                line_total=i.line_total,
                thumb_url=storage.url(thumbs[i.product_id]) if thumbs.get(i.product_id) else None,
            )
            for i in items
        ],
        items_total=order.items_total,
        order_discount=order.order_discount,
        food_net=order.food_net,
        service_fee=order.service_fee,
        rider_fee=order.rider_fee,
        till_amount=order.till_amount,
        rider_fee_cash=order.rider_fee - order.rider_fee_in_till,
        delivery_code=order.delivery_code,
        customer_trans_code=order.customer_trans_code,
        distance_km=order.distance_km,
        landmark=order.landmark,
        expires_at=order.expires_at if order.status in ("awaiting_payment",) else None,
        prep_minutes=order.prep_minutes,
        reason=order.reason,
        can_cancel=order.status in orders.CANCELLABLE,
        created_at=order.created_at,
        events=[
            TrackEvent(status=e.to_status, at=e.created_at)
            for e in events
            if e.from_status != e.to_status  # notes (e.g. rider assigned) aren't steps
        ],
        rider_name=rider.name.split(" ")[0] if rider and on_the_way else None,
        rider_phone=rider.phone if rider and on_the_way else None,
        rider_photo_url=(
            storage.url(profile.photo_key)
            if on_the_way and profile is not None and profile.photo_key
            else None
        ),
        fee_question=order.fee_not_paid_at is not None and order.customer_fee_answer is None,
    )


@router.post("/track/{token}/cancel", dependencies=[Depends(limit("cancel", 10))])
async def cancel(token: str, session: Session):
    order = await _by_token(session, token)
    order = await orders.cancel_by_customer(session, order.id, utcnow())
    await session.commit()
    return {"status": order.status}


# --- Order history (DECISIONS D20) -----------------------------------------------------------
# There are no customer accounts: the phone remembers its orders' tracking tokens and asks for
# all of them at once. A token is the secret, so nobody can list someone else's orders by phone.


class HistoryIn(Input):
    tokens: list[Annotated[str, Field(min_length=10, max_length=64)]] = Field(max_length=200)


class HistoryOut(Schema):
    token: str
    code: str
    hotel_name: str
    hotel_slug: str
    status: str
    type: str
    payment_method: str
    created_at: datetime
    till_amount: int
    paid: int  # money received (M-Pesa or cash)
    refunded: int  # refunds approved
    platform_bonus: int
    items: list[str]


@router.post(
    "/track/history",
    response_model=list[HistoryOut],
    dependencies=[Depends(limit("history", 30))],
)
async def history(body: HistoryIn, session: Session):
    if not body.tokens:
        return []
    rows = (
        await session.execute(
            select(Order, Hotel.name, Hotel.slug)
            .join(Hotel, Hotel.id == Order.hotel_id)
            .where(Order.tracking_token.in_(set(body.tokens)))
            .order_by(Order.created_at.desc())
        )
    ).all()
    ids = [o.id for o, _, _ in rows]
    items: dict = {}
    for oid, name, qty in (
        await session.execute(
            select(OrderItem.order_id, OrderItem.name_snapshot, OrderItem.quantity)
            .where(OrderItem.order_id.in_(ids))
            .order_by(OrderItem.id)
        )
    ).all():
        items.setdefault(oid, []).append(f"{qty}× {name}")
    paid = dict(
        (
            await session.execute(
                select(LedgerEntry.order_id, func.sum(LedgerEntry.amount))
                .where(LedgerEntry.order_id.in_(ids), LedgerEntry.entry_type.in_(ledger.PAYMENT_IN))
                .group_by(LedgerEntry.order_id)
            )
        ).all()
    )
    refunded = dict(
        (
            await session.execute(
                select(Refund.order_id, func.sum(Refund.amount))
                .where(Refund.order_id.in_(ids))
                .group_by(Refund.order_id)
            )
        ).all()
    )
    return [
        HistoryOut(
            token=o.tracking_token,
            code=o.code,
            hotel_name=hotel_name,
            hotel_slug=slug,
            status=o.status,
            type=o.type,
            payment_method=o.payment_method,
            created_at=o.created_at,
            till_amount=o.till_amount,
            paid=int(paid.get(o.id) or 0),
            refunded=int(refunded.get(o.id) or 0),
            platform_bonus=o.platform_bonus,
            items=items.get(o.id, []),
        )
        for o, hotel_name, slug in rows
    ]


class FeeAnswerIn(Input):
    paid: bool


@router.post("/track/{token}/rider-fee-answer", dependencies=[Depends(limit("fee_answer", 10))])
async def rider_fee_answer(token: str, body: FeeAnswerIn, session: Session):
    """D8: the customer says whether they paid the rider's cash fee."""
    order = await _by_token(session, token)
    order = await delivery.customer_answer(session, order, "yes" if body.paid else "no", utcnow())
    await session.commit()
    return {"answer": order.customer_fee_answer}
