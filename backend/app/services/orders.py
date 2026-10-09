"""Quotes and order placement.

Placement is idempotent: the Idempotency-Key row is inserted with ON CONFLICT DO NOTHING in the
same transaction that creates the order. Concurrent duplicates block on the unique index until
the first transaction commits, then read and return the same order.
"""

import hashlib
import json
import secrets
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import (
    Category,
    Customer,
    Discount,
    Hotel,
    IdempotencyKey,
    Order,
    OrderEvent,
    OrderItem,
    Product,
    PromoRedemption,
)
from app.payments import hook as payments_hook
from app.schemas.orders import OrderIn, QuoteIn, QuoteLineOut, QuoteOut
from app.services import bonus, catalogue, events, hours, ledger, pricing, routing, settings
from app.services.settings import PlatformSettings

IDEMPOTENCY_TTL = timedelta(hours=24)
CODE_ALPHABET = "ACDEFGHJKMNPQRTUVWXY34679"  # no 0/O, 1/I/L, 2/Z, 5/S, 8/B look-alikes
EAT_IN_MIN_NOTICE = timedelta(minutes=10)
EAT_IN_MAX_AHEAD = timedelta(hours=12)
CANCELLABLE = ("awaiting_payment", "checking_payment", "paid")


@dataclass
class Priced:
    hotel: Hotel
    quote: pricing.Quote
    settings: PlatformSettings
    customer: Customer | None
    promo: Discount | None
    distance_km: float | None = None  # hotel -> customer pin, straight line
    rider_fee_estimated: bool = False  # no pin yet: showing the nearest band ("from KES X")
    too_far: bool = False  # pin beyond the furthest delivery distance
    distance_method: str | None = None  # road | estimated | straight
    stamps: bonus.StampCard | None = None


def _pricing_error(e: pricing.PricingError) -> AppError:
    return AppError(422, e.code, e.message)


async def _hotel_by_slug(session: AsyncSession, slug: str) -> Hotel:
    stmt = select(Hotel).where(Hotel.slug == slug)
    hotel = (await session.execute(stmt)).scalar_one_or_none()
    if hotel is None:
        raise AppError(404, "not_found", "Hotel not found")
    return hotel


async def _catalogue(
    session: AsyncSession, hotel_id: uuid.UUID, product_ids: set[uuid.UUID], now: datetime
) -> dict[uuid.UUID, pricing.ProductInfo]:
    """Pricing inputs for the cart's products, read from this hotel only. Products whose
    category is outside its time window count as unavailable."""
    rows = (
        await session.execute(
            select(Product, Category)
            .join(Category, Category.id == Product.category_id)
            .where(Product.hotel_id == hotel_id, Product.id.in_(product_ids))
        )
    ).all()
    options = await catalogue.options_by_product(
        session, [p.id for p, _ in rows], include_archived=True
    )
    out = {}
    for p, c in rows:
        in_window = hours.category_available(c.available_from, c.available_to, now)
        out[p.id] = pricing.ProductInfo(
            id=p.id,
            name=p.name,
            price=p.price,
            options={
                o.id: pricing.OptionInfo(o.id, o.group_name, o.name, o.price_delta, o.is_archived)
                for o in options[p.id]
            },
            is_sold_out=p.is_sold_out,
            is_archived=p.is_archived or not in_window,
        )
    return out


def _discount_info(d: Discount, uses: int = 0) -> pricing.DiscountInfo:
    return pricing.DiscountInfo(
        id=d.id,
        scope=d.scope,
        kind=d.kind,
        value=d.value,
        starts_at=d.starts_at,
        ends_at=d.ends_at,
        product_id=d.product_id,
        min_spend=d.min_spend,
        promo_code=d.promo_code,
        max_uses=d.max_uses,
        uses_so_far=uses,
        is_active=d.is_active,
        days_mask=d.days_mask,
        daily_from=d.daily_from,
        daily_to=d.daily_to,
    )


async def price(
    session: AsyncSession, body: QuoteIn, now: datetime, *, lock_promo: bool = False
) -> Priced:
    hotel = await _hotel_by_slug(session, body.hotel_slug)
    if body.type == "delivery" and await payments_hook.stk_enabled_for(session, hotel.id):
        # Paid by STK Push: the rider fee is part of the one payment and goes to the rider's
        # wallet, so the customer owes nothing at the door (quote and order both come through here).
        body.rider_fee_mode = "included"
    values, _ = await settings.load(session)
    products = await _catalogue(session, hotel.id, {ln.product_id for ln in body.lines}, now)

    automatic = (
        (
            await session.execute(
                select(Discount).where(Discount.hotel_id == hotel.id, Discount.promo_code.is_(None))
            )
        )
        .scalars()
        .all()
    )

    promo = None
    promo_info = None
    phone_used = False
    code = (body.promo_code or "").strip().upper()
    if code:
        stmt = select(Discount).where(Discount.hotel_id == hotel.id, Discount.promo_code == code)
        if lock_promo:
            stmt = stmt.with_for_update()  # serialises the total-use limit check
        promo = (await session.execute(stmt)).scalar_one_or_none()
        if promo is not None:
            uses = await session.scalar(
                select(func.count())
                .select_from(PromoRedemption)
                .where(PromoRedemption.discount_id == promo.id)
            )
            promo_info = _discount_info(promo, uses or 0)
            if body.phone:
                phone_used = bool(
                    await session.scalar(
                        select(func.count())
                        .select_from(PromoRedemption)
                        .where(
                            PromoRedemption.discount_id == promo.id,
                            PromoRedemption.phone == body.phone,
                        )
                    )
                )

    customer = await session.get(Customer, body.phone) if body.phone else None

    # Rider fee by distance from the hotel.
    rates = settings.effective_for_hotel(values, hotel)
    distance = None
    estimated = too_far = False
    distance_method = None
    if body.type == "delivery":
        if hotel.lat is not None and body.lat is not None and body.lng is not None:
            d = await routing.distance(
                hotel.lat, hotel.lng, body.lat, body.lng, values.distance_method
            )
            distance, distance_method = d.km, d.method
            fee = values.rider_fee_at(distance)
            if fee is None:
                too_far = True
                fee = values.rider_fee_at(values.max_delivery_km) or 0
        else:
            estimated = True
            fee = values.base_rider_fee
        rates = replace(rates, rider_fee=fee)
    bonuses, card = await bonus.offer(
        session,
        values,
        customer,
        rider_fee=rates.rider_fee if body.type == "delivery" else 0,
        now=now,
        placing=lock_promo,
    )
    try:
        quote = pricing.calculate(
            cart=[
                pricing.CartLine(ln.product_id, ln.quantity, tuple(ln.option_ids))
                for ln in body.lines
            ],
            products=products,
            discounts=[_discount_info(d) for d in automatic],
            order_type=body.type,
            rider_fee_mode=body.rider_fee_mode,
            rates=rates,
            now=now,
            promo_code=code or None,
            promo=promo_info,
            phone_used_promo=phone_used,
            bonuses=bonuses,
        )
    except pricing.PricingError as e:
        raise _pricing_error(e) from None
    return Priced(
        hotel,
        quote,
        values,
        customer,
        promo if quote.promo_discount_id else None,
        distance_km=distance,
        rider_fee_estimated=estimated,
        too_far=too_far,
        distance_method=distance_method,
        stamps=card,
    )


def first_time(customer: Customer | None) -> bool:
    return customer is None or (customer.completed_orders == 0 and not customer.trusted)


def cash_cap(p: Priced) -> int | None:
    return p.settings.first_time_cash_cap if first_time(p.customer) else None


def option_b_allowed(customer: Customer | None) -> bool:
    return customer is None or not customer.option_b_blocked


def quote_out(p: Priced) -> QuoteOut:
    q = p.quote
    return QuoteOut(
        lines=[
            QuoteLineOut(
                product_id=ln.product_id,
                name=ln.name,
                unit_price=ln.unit_price,
                options=[o.name for o in ln.options],
                options_price=ln.options_price,
                quantity=ln.quantity,
                line_discount=ln.line_discount,
                line_total=ln.line_total,
            )
            for ln in q.lines
        ],
        items_total=q.items_total,
        order_discount=q.order_discount,
        food_net=q.food_net,
        service_fee=q.service_fee,
        eat_in_fee=q.eat_in_fee,
        rider_fee=q.rider_fee,
        rider_fee_in_till=q.rider_fee_in_till,
        rider_fee_cash=q.rider_fee - q.rider_fee_in_till,
        till_amount=q.till_amount,
        promo_applied=q.promo_discount_id is not None,
        promo_error=q.promo_error,
        option_b_allowed=option_b_allowed(p.customer),
        cash_allowed=False,  # D34: every order is paid first, by M-Pesa
        cash_cap=None,
        distance_km=p.distance_km,
        rider_fee_estimated=p.rider_fee_estimated,
        too_far=p.too_far,
        max_delivery_km=p.settings.max_delivery_km,
        platform_bonus=q.platform_bonus,
        bonus_kind=q.bonus_kind,
        free_delivery_min_food=p.settings.free_delivery_min_food or None,
        stamp_every=p.stamps.every if p.stamps else 0,
        stamps_have=p.stamps.have if p.stamps else 0,
        stamp_reward=p.settings.stamp_reward,
    )


def point_in_zone(lat: float, lng: float, zone: list[list[float]]) -> bool:
    """Ray casting on [lng, lat] points. Fine at a town's scale."""
    inside = False
    j = len(zone) - 1
    for i in range(len(zone)):
        xi, yi = zone[i]
        xj, yj = zone[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


async def _check_can_order(session: AsyncSession, body: OrderIn, p: Priced, now: datetime):
    hotel_hours = (await catalogue.hotel_hours(session, [p.hotel.id]))[p.hotel.id]
    status = hours.open_status(p.hotel, hotel_hours, now, p.settings.order_cutoff_minutes)
    if not status.is_open:
        messages = {
            "paused": "This hotel is not taking orders right now",
            "not_accepting": "This hotel is not taking orders right now",
            "closed": "This hotel is closed for orders",
        }
        raise AppError(409, "hotel_closed", messages.get(status.state, "Closed"))

    customer = p.customer
    if customer is not None and customer.blocklisted:
        raise AppError(403, "blocked", "This number cannot place orders. Contact support.")
    if body.rider_fee_mode == "cash" and not option_b_allowed(customer):
        raise AppError(
            409,
            "option_b_unavailable",
            "Delivery is not available on this number right now. You can order for pickup, "
            "or contact support.",
        )
    if body.payment_method != "mpesa":
        # D34: nothing is prepared until it is paid, so nobody can order and not turn up.
        raise AppError(
            422,
            "cash_not_accepted",
            "Every order is paid first with M-Pesa, straight to the hotel's Till.",
            extra={"field": "payment_method"},
        )
    if body.type == "eat_in":
        soonest, latest = now + EAT_IN_MIN_NOTICE, now + EAT_IN_MAX_AHEAD
        if not soonest <= body.arrive_at <= latest:
            raise AppError(
                422, "bad_arrival", "Choose an arrival time from 10 minutes to 12 hours from now"
            )
    if body.type == "delivery":
        if p.too_far:
            km = p.settings.max_delivery_km
            raise AppError(
                422, "too_far", f"That's more than {km:g} km from {p.hotel.name}. Choose pickup."
            )
        # With a drawn area, the pin must be inside it. Without one, the limit is the
        # furthest delivery distance from the hotel, which needs the hotel's location.
        zone = p.settings.delivery_zone
        if zone:
            if not point_in_zone(body.lat, body.lng, zone):
                raise AppError(422, "outside_zone", "That pin is outside our delivery area")
        elif p.hotel.lat is None:
            raise AppError(
                409, "delivery_unavailable", f"{p.hotel.name} doesn't deliver yet. Choose pickup."
            )


def fingerprint(body: OrderIn) -> str:
    data = body.model_dump(mode="json")
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def _code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))


async def place(
    session: AsyncSession, body: OrderIn, idempotency_key: str, now: datetime
) -> tuple[Order, bool]:
    """Return (order, created). Runs in the caller's transaction; the caller commits."""
    request_hash = fingerprint(body)
    claimed = await session.execute(
        insert(IdempotencyKey)
        .values(key=idempotency_key, request_hash=request_hash, expires_at=now + IDEMPOTENCY_TTL)
        .on_conflict_do_nothing()
        .returning(IdempotencyKey.key)
    )
    if claimed.scalar_one_or_none() is None:
        existing = await session.get(IdempotencyKey, idempotency_key)
        if existing.request_hash != request_hash:
            raise AppError(
                409, "idempotency_conflict", "This checkout was already used. Please start again."
            )
        if existing.order_id is None:  # unreachable once the first transaction committed
            raise AppError(409, "in_progress", "Your order is being placed. Please wait.")
        return await session.get(Order, existing.order_id), False

    p = await price(session, body, now, lock_promo=True)
    # A promo the customer typed but can't use is the real reason, not "price changed".
    if p.quote.promo_error and body.promo_code:
        raise AppError(409, p.quote.promo_error, "That promo code can't be used")
    if p.quote.till_amount != body.expected_total:
        raise AppError(
            409,
            "price_changed",
            "Prices changed. Please check the new total.",
            extra={"quote": quote_out(p).model_dump(mode="json")},
        )
    await _check_can_order(session, body, p, now)

    await session.execute(
        insert(Customer)
        .values(phone=body.phone, name=body.name, last_order_at=now)
        .on_conflict_do_update(
            index_elements=[Customer.phone], set_={"name": body.name, "last_order_at": now}
        )
    )

    q = p.quote
    discount_id = q.order_discount_id or q.promo_discount_id
    order = None
    for _ in range(5):
        candidate = Order(
            code=_code(),
            tracking_token=secrets.token_urlsafe(24),
            hotel_id=p.hotel.id,
            customer_phone=body.phone,
            customer_name=body.name,
            type=body.type,
            rider_fee_mode=body.rider_fee_mode,
            payment_method=body.payment_method,
            status="awaiting_payment",
            lat=body.lat if body.type == "delivery" else None,
            lng=body.lng if body.type == "delivery" else None,
            landmark=body.landmark.strip() if body.type == "delivery" else None,
            items_total=q.items_total,
            order_discount=q.order_discount,
            food_net=q.food_net,
            service_fee=q.service_fee,
            rider_fee=q.rider_fee,
            rider_fee_in_till=q.rider_fee_in_till,
            till_amount=q.till_amount,
            commission_bp=q.commission_bp,
            commission_amount=q.commission_amount,
            platform_bonus=q.platform_bonus,
            bonus_kind=q.bonus_kind,
            eat_in_fee=q.eat_in_fee,
            arrive_at=body.arrive_at if body.type == "eat_in" else None,
            discount_id=discount_id,
            delivery_code=f"{secrets.randbelow(10_000):04d}",  # handover PIN, all order types
            # Snapshot: the distance the fee was priced on; customer, hotel and rider all see it.
            distance_km=p.distance_km if body.type == "delivery" else None,
            # Cash pickup is paid at collection, so it never expires.
            expires_at=(
                now + timedelta(minutes=p.settings.unpaid_expiry_minutes)
                if body.payment_method == "mpesa"
                else None
            ),
        )
        try:
            async with session.begin_nested():
                session.add(candidate)
                await session.flush()
            order = candidate
            break
        except IntegrityError:
            continue  # order code collision: try another
    if order is None:
        raise AppError(503, "busy", "Please try again")

    session.add_all(
        OrderItem(
            order_id=order.id,
            product_id=ln.product_id,
            name_snapshot=ln.name,
            unit_price=ln.unit_price,
            options_snapshot=[
                {"id": str(o.id), "group": o.group_name, "name": o.name, "price": o.price_delta}
                for o in ln.options
            ],
            options_price=ln.options_price,
            quantity=ln.quantity,
            line_discount=ln.line_discount,
            line_total=ln.line_total,
        )
        for ln in q.lines
    )
    if p.promo is not None:
        try:
            async with session.begin_nested():
                session.add(
                    PromoRedemption(discount_id=p.promo.id, phone=body.phone, order_id=order.id)
                )
                await session.flush()
        except IntegrityError:
            raise AppError(409, "promo_already_used", "That promo code can't be used") from None
    session.add(OrderEvent(order_id=order.id, to_status=order.status, actor_type="customer"))
    await session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.key == idempotency_key)
        .values(order_id=order.id)
    )
    events.order_changed(session, order, {"new_order": True})
    await session.flush()
    return order, True


async def cancel_by_customer(session: AsyncSession, order_id: uuid.UUID, now: datetime) -> Order:
    """Cancel before the hotel accepts. A paid order gets a full refund record."""
    order = (
        await session.execute(select(Order).where(Order.id == order_id).with_for_update())
    ).scalar_one()
    if order.status == "cancelled":
        return order  # repeat tap
    if order.status not in CANCELLABLE:
        raise AppError(409, "not_cancellable", "The hotel has already accepted this order")
    previous = order.status
    order.status = "cancelled"
    order.closed_at = now
    order.reason = "Cancelled by customer"
    session.add(
        OrderEvent(
            order_id=order.id,
            from_status=previous,
            to_status="cancelled",
            actor_type="customer",
            reason=order.reason,
        )
    )
    await session.flush()
    if previous == "paid":
        await ledger.refund_rest(
            session, order, reason="Cancelled by customer before acceptance", approved_by=None
        )
    return order
