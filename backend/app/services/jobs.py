"""Background jobs. Each is safe to run twice: conditional updates and
"one open review item per order and type" make a repeat a no-op.

They run in the API process every minute (one process at launch, spec section 4). Tests call
the functions directly.
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.time import utcnow
from app.payments import scheduler as payments_scheduler
from app.models import Hotel, Order, OrderEvent, Payment, ReviewItem
from app.services import (
    billing,
    catalogue,
    delivery,
    events,
    forwarder,
    hours,
    order_flow,
    payments,
    settings,
    tracking,
)

log = logging.getLogger("app.jobs")


async def expire_unpaid(session: AsyncSession, now: datetime) -> int:
    """M-Pesa orders still awaiting payment after their expiry time. Orders where the customer
    entered a code are in checking_payment and never expire here."""
    rows = (
        (
            await session.execute(
                update(Order)
                .where(
                    Order.status == "awaiting_payment",
                    Order.payment_method == "mpesa",
                    Order.expires_at.is_not(None),
                    Order.expires_at < now,
                )
                .values(status="expired", closed_at=now, reason="Not paid in time")
                .returning(Order.id)
            )
        )
        .scalars()
        .all()
    )
    for oid in rows:
        session.add(
            OrderEvent(
                order_id=oid,
                from_status="awaiting_payment",
                to_status="expired",
                actor_type="system",
            )
        )
        events.order_changed(session, await session.get(Order, oid))
    await session.flush()
    return len(rows)


async def flag_missing_payments(session: AsyncSession, now: datetime) -> int:
    """Code entered, no matching payment 5 minutes later: alert the hotel."""
    since = now - payments.NO_SMS_AFTER
    orders = (
        (
            await session.execute(
                select(Order)
                .join(OrderEvent, OrderEvent.order_id == Order.id)
                .where(
                    Order.status == "checking_payment",
                    OrderEvent.to_status == "checking_payment",
                    OrderEvent.created_at < since,
                )
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    flagged = 0
    for o in orders:
        has_payment = await session.scalar(select(Payment.id).where(Payment.order_id == o.id))
        if has_payment:
            continue
        await payments.open_review(
            session,
            type="no_sms",
            hotel_id=o.hotel_id,
            order_id=o.id,
            reason=(
                f"Customer entered {o.customer_trans_code} but the payment hasn't been seen. "
                "Check the Till phone."
            ),
        )
        flagged += 1
    return flagged


async def refund_late_payments_at_closing(session: AsyncSession, now: datetime) -> int:
    """A late payment still unresolved when the hotel closes defaults to Refund."""
    values, _ = await settings.load(session)
    items = (
        (
            await session.execute(
                select(ReviewItem).where(
                    ReviewItem.type == "late_payment",
                    ReviewItem.status == "open",
                    ReviewItem.payment_id.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    done = 0
    for item in items:
        hotel = await session.get(Hotel, item.hotel_id)
        hrs = (await catalogue.hotel_hours(session, [hotel.id]))[hotel.id]
        state = hours.open_status(hotel, hrs, now, values.order_cutoff_minutes).state
        if state == "closed":
            await payments.resolve(session, item, "refund", None, now)
            done += 1
    return done


async def run_all(sessionmaker: async_sessionmaker, now: datetime | None = None) -> dict[str, int]:
    now = now or utcnow()
    out = {}
    for name, job in (
        ("expired", expire_unpaid),
        ("no_sms", flag_missing_payments),
        ("late_refunds", refund_late_payments_at_closing),
        ("auto_rejected", order_flow.auto_reject_late),
        ("fee_answers_timed_out", delivery.answer_timeouts),
        ("billing", billing.weekly_job),
        ("rider_payouts", payments_scheduler.run),  # no-op unless PAYMENTS_ENABLED
        ("nonces_pruned", forwarder.prune_nonces),
        ("pings_pruned", tracking.prune),
    ):
        async with sessionmaker() as session:
            try:
                out[name] = await job(session, now)
                await session.commit()
            except Exception:  # one failing job must not stop the others
                await session.rollback()
                log.exception("job %s failed", name)
    return out


async def loop(sessionmaker: async_sessionmaker, every_s: int = 60) -> None:
    while True:
        try:
            result = await run_all(sessionmaker)
            if any(result.values()):
                log.info("jobs", extra={"extra_fields": result})
        except Exception:
            log.exception("job loop")
        await asyncio.sleep(every_s)
