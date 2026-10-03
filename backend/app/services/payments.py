"""Payments and matching (spec sections 6, 13, 14; DECISIONS D5, D17).

Every payment is a row in `payments` keyed by its unique M-Pesa transaction code, whatever its
source: cashier (manual), forwarder SMS (M8), or Daraja later. Confirmation runs the same checks
for all sources:

  1. the payment reached THIS hotel's Till,
  2. the amount equals the order total exactly (under/over go to review),
  3. it was paid after the order was created (2 minutes' tolerance),
  4. the code is not attached to any other order (unique constraint).

An order becomes Paid in one transaction with its ledger entries, under a row lock, with a
conditional status update, so a code can confirm at most one order exactly once.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Hotel, Order, OrderEvent, Payment, Product, ReviewItem
from app.models.orders import OrderItem
from app.services import events, ledger, names, settings

CODE_RE = re.compile(r"^[A-Z0-9]{10}$")
PAID_AT_TOLERANCE = timedelta(minutes=2)
NO_SMS_AFTER = timedelta(minutes=5)
PENDING = ("awaiting_payment", "checking_payment")


def normalize_code(raw: str) -> str:
    code = re.sub(r"\s+", "", raw or "").upper()
    if not CODE_RE.match(code):
        raise AppError(422, "bad_code", "M-Pesa codes are 10 letters and numbers, e.g. SJK3ABC12D")
    return code


@dataclass(frozen=True)
class Outcome:
    result: str  # paid | underpaid | overpaid | late | wrong_hotel | too_old | pending
    order_status: str
    message: str


async def _lock_order(session: AsyncSession, order_id: uuid.UUID) -> Order:
    order = (
        await session.execute(select(Order).where(Order.id == order_id).with_for_update())
    ).scalar_one_or_none()
    if order is None:
        raise AppError(404, "not_found", "Order not found")
    return order


async def _event(session, order: Order, from_status: str, actor_type: str, actor_id, reason=None):
    session.add(
        OrderEvent(
            order_id=order.id,
            from_status=from_status,
            to_status=order.status,
            actor_type=actor_type,
            actor_id=actor_id,
            reason=reason,
        )
    )


async def open_review(
    session: AsyncSession,
    *,
    type: str,
    hotel_id: uuid.UUID | None,
    reason: str,
    order_id: uuid.UUID | None = None,
    payment_id: uuid.UUID | None = None,
    sms_message_id: uuid.UUID | None = None,
) -> ReviewItem:
    """One open item per (order, type): repeats return the existing one."""
    if order_id is not None:
        existing = (
            await session.execute(
                select(ReviewItem).where(
                    ReviewItem.order_id == order_id,
                    ReviewItem.type == type,
                    ReviewItem.status == "open",
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            # e.g. the customer reported a late payment first; the money has now arrived.
            if payment_id is not None and existing.payment_id is None:
                existing.payment_id = payment_id
                await session.flush()
            return existing
    if hotel_id is not None:
        events.emit(session, f"hotel:{hotel_id}", {"type": "review", "review_type": type})
    events.emit(session, "admin", {"type": "review", "review_type": type})
    item = ReviewItem(
        type=type,
        hotel_id=hotel_id,
        order_id=order_id,
        payment_id=payment_id,
        sms_message_id=sms_message_id,
        reason=reason,
    )
    session.add(item)
    await session.flush()
    return item


async def _mark_paid(
    session: AsyncSession, order: Order, payment: Payment, actor_type: str, actor_id, now
) -> bool:
    """Conditional update to Paid plus ledger entries, in the caller's transaction."""
    previous = order.status
    result = await session.execute(
        update(Order)
        .where(Order.id == order.id, Order.status.in_((*PENDING, "expired")))
        .values(status="paid", paid_at=now, closed_at=None)
        .returning(Order.status)
    )
    if result.scalar_one_or_none() is None:
        return False
    await session.refresh(order)
    await ledger.record_payment(
        session,
        order,
        amount=payment.amount,
        method="mpesa",
        reference=payment.trans_code,
        created_by=payment.confirmed_by,
    )
    await _event(session, order, previous, actor_type, actor_id)
    events.order_changed(session, order, {"new_paid": True})  # rings the hotel's order screen
    return True


async def apply_payment(
    session: AsyncSession,
    order: Order,
    payment: Payment,
    *,
    actor_type: str,
    actor_id: uuid.UUID | None,
    now: datetime,
) -> Outcome:
    """Run the confirmation checks for a payment already linked to a locked order."""
    hotel = await session.get(Hotel, order.hotel_id)
    values, _ = await settings.load(session)

    if payment.till_number != hotel.till_number:
        payment.status = "review"
        await open_review(
            session,
            type="unmatched_sms",
            hotel_id=order.hotel_id,
            order_id=order.id,
            payment_id=payment.id,
            reason=f"Paid to Till {payment.till_number}, not {hotel.till_number}",
        )
        return Outcome("wrong_hotel", order.status, "That payment went to a different Till")

    if payment.paid_at < order.created_at - PAID_AT_TOLERANCE:
        payment.status = "review"
        await open_review(
            session,
            type="unmatched_sms",
            hotel_id=order.hotel_id,
            order_id=order.id,
            payment_id=payment.id,
            reason="Payment is older than the order (old code?)",
        )
        return Outcome("too_old", order.status, "That payment was made before this order")

    if order.status == "expired":
        # D5: money after expiry. Within the grace period the cashier chooses Reinstate or Refund.
        payment.status = "review"
        grace = timedelta(hours=values.late_payment_grace_hours)
        late_by = (payment.paid_at - order.expires_at) if order.expires_at else timedelta(0)
        reason = "Paid after the order expired"
        if late_by > grace:
            reason += " (after the grace period)"
        await open_review(
            session,
            type="late_payment",
            hotel_id=order.hotel_id,
            order_id=order.id,
            payment_id=payment.id,
            reason=reason,
        )
        return Outcome(
            "late",
            order.status,
            "Payment received after the order expired. The hotel is reviewing.",
        )

    if order.status not in PENDING:
        # Already paid / cancelled: never confirm twice; flag the extra money.
        payment.status = "review"
        await open_review(
            session,
            type="overpaid",
            hotel_id=order.hotel_id,
            order_id=order.id,
            payment_id=payment.id,
            reason=f"Extra payment on an order that is already {order.status}",
        )
        return Outcome("pending", order.status, "This order is already settled")

    if payment.amount < order.till_amount:
        payment.status = "review"
        if order.status == "awaiting_payment":
            order.status = "checking_payment"
            await _event(session, order, "awaiting_payment", actor_type, actor_id, "underpaid")
        short = order.till_amount - payment.amount
        await open_review(
            session,
            type="underpaid",
            hotel_id=order.hotel_id,
            order_id=order.id,
            payment_id=payment.id,
            reason=f"Paid KES {payment.amount:,}, KES {short:,} short",
        )
        return Outcome(
            "underpaid",
            order.status,
            f"You paid KES {payment.amount:,}. "
            f"The hotel will contact you about the KES {short:,} balance.",
        )

    payment.status = "matched"
    await _mark_paid(session, order, payment, actor_type, actor_id, now)
    if payment.amount > order.till_amount:
        extra = payment.amount - order.till_amount
        await open_review(
            session,
            type="overpaid",
            hotel_id=order.hotel_id,
            order_id=order.id,
            payment_id=payment.id,
            reason=f"Paid KES {extra:,} more than the total: refund the difference",
        )
        return Outcome(
            "overpaid", "paid", f"Payment received. KES {extra:,} extra will be refunded."
        )
    return Outcome("paid", "paid", "Payment received")


async def _insert_payment(session: AsyncSession, **values) -> Payment | None:
    """Insert a payment; None if that transaction code already exists (unique guard)."""
    stmt = insert(Payment).values(**values).on_conflict_do_nothing().returning(Payment.id)
    pid = (await session.execute(stmt)).scalar_one_or_none()
    return await session.get(Payment, pid) if pid else None


async def confirm_manual(
    session: AsyncSession,
    order_id: uuid.UUID,
    *,
    code: str,
    amount: int,
    paid_at: datetime | None,
    cashier_id: uuid.UUID,
    now: datetime,
) -> Outcome:
    """Cashier read the Till phone's SMS and typed the code and amount (spec section 6)."""
    code = normalize_code(code)
    if amount <= 0:
        raise AppError(422, "bad_amount", "Enter the amount shown in the M-Pesa message")
    order = await _lock_order(session, order_id)
    hotel = await session.get(Hotel, order.hotel_id)
    if order.payment_method != "mpesa":
        raise AppError(409, "not_mpesa", "This is a cash order. Use “Cash received”.")

    existing = (
        await session.execute(select(Payment).where(Payment.trans_code == code))
    ).scalar_one_or_none()
    if existing is not None:
        if existing.order_id == order.id:
            return Outcome(
                "paid" if order.status == "paid" else "pending", order.status, "Already recorded"
            )
        if existing.order_id is not None:
            other = await session.get(Order, existing.order_id)
            raise AppError(409, "code_used", f"That code was already used for order #{other.code}")
        # An unmatched payment (e.g. from an SMS) with this code: link it to this order.
        if existing.till_number != hotel.till_number:
            raise AppError(409, "wrong_till", "That code was paid to a different Till")
        existing.order_id = order.id
        existing.confirmed_by = cashier_id
        payment = existing
    else:
        payment = await _insert_payment(
            session,
            till_number=hotel.till_number,
            trans_code=code,
            amount=amount,
            paid_at=paid_at or now,
            source="manual",
            order_id=order.id,
            status="review",
            confirmed_by=cashier_id,
        )
        if payment is None:  # lost a race on the same code
            raise AppError(409, "code_used", "That code was just recorded. Refresh and check.")
    if order.customer_trans_code is None:
        order.customer_trans_code = code
    await session.flush()
    return await apply_payment(
        session, order, payment, actor_type="staff", actor_id=cashier_id, now=now
    )


async def submit_customer_code(
    session: AsyncSession, order_id: uuid.UUID, raw_code: str, now: datetime
) -> Outcome:
    """Customer typed their M-Pesa code (D5: this pauses expiry). If the payment is already
    known (from an SMS), it is matched straight away."""
    code = normalize_code(raw_code)
    order = await _lock_order(session, order_id)
    if order.payment_method != "mpesa":
        raise AppError(409, "not_mpesa", "Pay cash at the counter for this order")
    if order.status not in (*PENDING, "expired"):
        return Outcome("pending", order.status, "This order is already settled")

    used = (
        await session.execute(select(Payment).where(Payment.trans_code == code))
    ).scalar_one_or_none()
    if used is not None and used.order_id not in (None, order.id):
        raise AppError(409, "code_used", "That M-Pesa code was already used for another order")

    order.customer_trans_code = code
    if order.status == "awaiting_payment":
        order.status = "checking_payment"
        await _event(session, order, "awaiting_payment", "customer", None, "code entered")
    await session.flush()
    events.order_changed(session, order)

    if used is not None:  # the SMS arrived first: match now
        used.order_id = order.id
        await session.flush()
        await _close_unmatched(session, used, f"customer_code:{order.code}", now)
        return await apply_payment(
            session, order, used, actor_type="system", actor_id=None, now=now
        )

    if order.status == "expired":
        await open_review(
            session,
            type="late_payment",
            hotel_id=order.hotel_id,
            order_id=order.id,
            reason=f"Customer says they paid ({code}) after the order expired. Check the Till.",
        )
        return Outcome(
            "late", order.status, "Your order had expired. The hotel will check your payment."
        )
    return Outcome("pending", order.status, "Thanks! We're checking your payment with the hotel.")


async def record_incoming(
    session: AsyncSession,
    *,
    till_number: str,
    code: str,
    amount: int,
    paid_at: datetime,
    source: str,
    phone_digits: str | None = None,
    payer_name: str | None = None,
    sms_message_id: uuid.UUID | None = None,
    now: datetime,
) -> tuple[Payment, Outcome | None]:
    """A payment seen on a Till (the forwarder app, M8; or the admin's paste-SMS tool).
    Stored first, then matched; repeats are no-ops (unique code).

    With the customer's code: that order, whatever the payer's name (people pay for each
    other). Without a code, an order is chosen only when exactly one waiting order fits the
    amount, the visible phone digits and, when the SMS has a name, at least one checkout name
    (D25); two names beat one. Anything else goes to the hotel's review queue."""
    code = normalize_code(code)
    payment = await _insert_payment(
        session,
        till_number=till_number,
        trans_code=code,
        amount=amount,
        paid_at=paid_at,
        source=source,
        sms_message_id=sms_message_id,
        status="review",
        payer_name=(" ".join(payer_name.split())[:120] or None) if payer_name else None,
    )
    if payment is None:
        existing = (
            await session.execute(select(Payment).where(Payment.trans_code == code))
        ).scalar_one()
        return existing, None

    hotel = (
        await session.execute(select(Hotel).where(Hotel.till_number == till_number))
    ).scalar_one_or_none()
    if hotel is None:
        # The platform's own Till (settlements, M7) or an unknown Till.
        return payment, None

    # 1. The customer already entered this code.
    order = (
        await session.execute(
            select(Order)
            .where(
                Order.hotel_id == hotel.id,
                Order.customer_trans_code == code,
                Order.status.in_((*PENDING, "expired")),
            )
            .order_by(Order.created_at)
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()

    # 2. No code entered: match only if exactly one pending order at this hotel has the same
    #    amount and (when known) the same visible phone digits (spec section 6).
    if order is None:
        candidates = (
            (
                await session.execute(
                    select(Order).where(
                        Order.hotel_id == hotel.id,
                        Order.status.in_(PENDING),
                        Order.customer_trans_code.is_(None),
                        Order.till_amount == amount,
                        Order.created_at >= paid_at - timedelta(hours=2),
                    )
                )
            )
            .scalars()
            .all()
        )
        if phone_digits:
            tail = re.sub(r"\D", "", phone_digits)[-3:]
            candidates = [o for o in candidates if o.customer_phone.endswith(tail)]
        if payment.payer_name and candidates:
            scored = [
                (names.match(o.customer_name, payment.payer_name) or 0, o) for o in candidates
            ]
            best = max(s for s, _ in scored)
            candidates = [o for s, o in scored if s == best] if best > 0 else []
            if not candidates:
                near = ", ".join(f"#{o.code} ({o.customer_name})" for _, o in scored[:3])
                await open_review(
                    session,
                    type="unmatched_sms",
                    hotel_id=hotel.id,
                    payment_id=payment.id,
                    sms_message_id=sms_message_id,
                    reason=(
                        f"KES {amount:,} from {payment.payer_name} ({code}): the amount fits "
                        f"{near} but the name doesn't. Check, then use Match to order."
                    ),
                )
                return payment, None
        if len(candidates) == 1:
            order = await _lock_order(session, candidates[0].id)
        elif len(candidates) > 1:
            several = ", ".join(f"#{o.code} ({o.customer_name})" for o in candidates[:4])
            await open_review(
                session,
                type="unmatched_sms",
                hotel_id=hotel.id,
                payment_id=payment.id,
                sms_message_id=sms_message_id,
                reason=(
                    f"KES {amount:,} received ({code}"
                    f"{f', from {payment.payer_name}' if payment.payer_name else ''}) fits "
                    f"{len(candidates)} orders equally: {several}. Ask the customer, then use "
                    "Match to order."
                ),
            )
            return payment, None

    if order is None:
        await open_review(
            session,
            type="unmatched_sms",
            hotel_id=hotel.id,
            payment_id=payment.id,
            sms_message_id=sms_message_id,
            reason=(
                f"KES {amount:,} received ({code}"
                f"{f', from {payment.payer_name}' if payment.payer_name else ''}) "
                "but no order could be matched"
            ),
        )
        return payment, None

    payment.order_id = order.id
    payment.name_match = names.match(order.customer_name, payment.payer_name)
    await session.flush()
    outcome = await apply_payment(
        session,
        order,
        payment,
        actor_type="forwarder" if source == "forwarder" else "system",
        actor_id=None,
        now=now,
    )
    return payment, outcome


async def record_reversal(session: AsyncSession, code: str, now: datetime) -> Payment | None:
    """M-Pesa reversed a payment: flag the linked order immediately (spec section 6)."""
    code = normalize_code(code)
    payment = (
        await session.execute(select(Payment).where(Payment.trans_code == code).with_for_update())
    ).scalar_one_or_none()
    if payment is None:
        return None
    payment.status = "reversed"
    order = await session.get(Order, payment.order_id) if payment.order_id else None
    await open_review(
        session,
        type="reversal",
        hotel_id=order.hotel_id if order else None,
        order_id=payment.order_id,
        payment_id=payment.id,
        reason=f"M-Pesa reversed {code}. Stop the order if it isn't out yet.",
    )
    return payment


# --- Cash at the counter -----------------------------------------------------------------------


async def cash_received(
    session: AsyncSession, order_id: uuid.UUID, cashier_id: uuid.UUID, now: datetime
) -> Order:
    order = await _lock_order(session, order_id)
    if order.payment_method != "cash":
        raise AppError(409, "not_cash", "This order is paid by M-Pesa")
    if order.status in ("cancelled", "rejected", "expired"):
        raise AppError(409, "closed", f"This order is {order.status}")
    await ledger.record_payment(
        session, order, amount=order.till_amount, method="cash", created_by=cashier_id
    )
    if order.paid_at is None:
        order.paid_at = now
    if order.status == "awaiting_payment":
        order.status = "paid"
        await _event(session, order, "awaiting_payment", "staff", cashier_id, "cash received")
    await session.flush()
    events.order_changed(session, order)
    return order


# --- Review resolution -------------------------------------------------------------------------

RESOLUTIONS = {
    "underpaid": ("refund", "accept_shortfall"),
    "overpaid": ("refund_difference", "dismiss"),
    "late_payment": ("reinstate", "refund"),
    "unmatched_sms": ("match_order", "dismiss"),
    "no_sms": ("dismiss",),
    "reversal": ("cancel_order", "dismiss"),
    "parse_failed": ("dismiss",),
    # Delivery items (D7, D8, D21): the super admin decides, never the hotel.
    "failed_delivery": ("customer_fault", "rider_fault", "hotel_fault"),
    "fee_dispute": ("pay_rider", "no_payment"),
}
ADMIN_TYPES = ("failed_delivery", "fee_dispute")


async def _items_available(session: AsyncSession, order: Order) -> bool:
    rows = (
        await session.execute(
            select(Product.is_sold_out, Product.is_archived)
            .join(OrderItem, OrderItem.product_id == Product.id)
            .where(OrderItem.order_id == order.id)
        )
    ).all()
    return all(not sold and not archived for sold, archived in rows)


async def resolve(
    session: AsyncSession,
    item: ReviewItem,
    action: str,
    user_id: uuid.UUID,
    now: datetime,
    *,
    order_code: str | None = None,
) -> ReviewItem:
    if item.status != "open":
        return item  # repeat tap
    allowed = RESOLUTIONS.get(item.type, ("dismiss",))
    if action not in allowed:
        raise AppError(422, "bad_action", f"Choose one of: {', '.join(allowed)}")
    if item.type in ADMIN_TYPES:
        from app.services import delivery  # delivery imports this module

        if item.type == "failed_delivery":
            await delivery.classify_failure(session, item, action, user_id, now)
        else:
            await delivery.resolve_fee_dispute(session, item, action, user_id, now)
        item.status = "resolved"
        item.resolution = action
        item.resolved_by = user_id
        item.resolved_at = now
        await session.flush()
        _resolved_event(session, item)
        return item
    order = await _lock_order(session, item.order_id) if item.order_id else None
    payment = await session.get(Payment, item.payment_id) if item.payment_id else None

    if action == "match_order":
        # The customer paid without sending their code and the amount didn't match a single
        # order: the cashier says which order it was for; the usual checks then run.
        if payment is None or payment.order_id is not None:
            raise AppError(409, "no_payment", "This payment is already linked to an order")
        code = (order_code or "").strip().lstrip("#").upper()
        target = (
            await session.execute(
                select(Order)
                .where(Order.code == code, Order.hotel_id == item.hotel_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if target is None:
            raise AppError(404, "order_not_found", f"No order #{code} at this hotel")
        if target.status not in (*PENDING, "expired") or await ledger.amount_paid(
            session, target.id
        ):
            raise AppError(409, "already_paid", f"Order #{code} is already paid or closed")
        payment.order_id = target.id
        item.order_id = target.id
        await session.flush()
        if target.status == "expired":
            await open_review(
                session,
                type="late_payment",
                hotel_id=target.hotel_id,
                order_id=target.id,
                payment_id=payment.id,
                reason=f"Payment {payment.trans_code} came after the order expired",
            )
        else:
            await apply_payment(
                session, target, payment, actor_type="staff", actor_id=user_id, now=now
            )
        item.status = "resolved"
        item.resolution = f"match_order:{code}"
        item.resolved_by = user_id
        item.resolved_at = now
        await session.flush()
        _resolved_event(session, item)
        return item

    if action in ("accept_shortfall", "reinstate"):
        if payment is None or order is None:
            raise AppError(409, "no_payment", "There is no payment to accept yet")
        if action == "reinstate" and not await _items_available(session, order):
            raise AppError(409, "items_unavailable", "Some items are sold out now. Refund instead.")
        payment.status = "matched"
        if not await _mark_paid(session, order, payment, "staff", user_id, now):
            raise AppError(409, "not_pending", f"The order is already {order.status}")
    elif action in ("refund", "refund_difference"):
        if payment is None or order is None:
            raise AppError(409, "no_payment", "There is no payment to refund")
        if action == "refund_difference":
            extra = payment.amount - order.till_amount
            await ledger.approve_refund(
                session,
                order.id,
                excess=extra,
                reason="Overpayment",
                approved_by=user_id,
                refund_id=uuid.uuid5(item.id, "refund"),
            )
        else:
            # The money was never accepted for the order: return all of it, no commission.
            await ledger.refund_unaccepted(
                session,
                order,
                amount=payment.amount,
                reference=payment.trans_code,
                reason=f"Review: {item.type}",
                approved_by=user_id,
                refund_id=uuid.uuid5(item.id, "refund"),
            )
            previous = order.status
            if previous in (*PENDING, "expired"):
                order.status = "cancelled"
                order.closed_at = now
                order.reason = "Payment refunded"
                await _event(session, order, previous, "staff", user_id, "payment refunded")
        payment.status = "matched"
    elif action == "cancel_order":
        if order and order.status not in ("cancelled", "rejected", "delivered", "collected"):
            previous = order.status
            order.status = "cancelled"
            order.closed_at = now
            order.reason = "Payment reversed by M-Pesa"
            await _event(session, order, previous, "staff", user_id, "payment reversed")
    item.status = "resolved"
    item.resolution = action
    item.resolved_by = user_id
    item.resolved_at = now
    await session.flush()
    _resolved_event(session, item)
    return item


async def _close_unmatched(
    session: AsyncSession, payment: Payment, resolution: str, now: datetime
) -> None:
    """The payment now belongs to an order, so its "which order was this for?" item is
    answered. Left open, it would offer a Match that can only fail."""
    items = (
        (
            await session.execute(
                select(ReviewItem).where(
                    ReviewItem.payment_id == payment.id,
                    ReviewItem.type == "unmatched_sms",
                    ReviewItem.status == "open",
                )
            )
        )
        .scalars()
        .all()
    )
    for item in items:
        item.status, item.resolution, item.resolved_at = "resolved", resolution, now
        _resolved_event(session, item)
    if items:
        await session.flush()


def _resolved_event(session: AsyncSession, item: ReviewItem) -> None:
    payload = {"type": "review", "resolved": True, "review_type": item.type}
    if item.hotel_id:
        events.emit(session, f"hotel:{item.hotel_id}", payload)
    events.emit(session, "admin", payload)
