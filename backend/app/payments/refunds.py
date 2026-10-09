"""Customer refunds by B2C. A cancelled or rejected order that was paid by STK gives the money
back to the phone that paid. Same never-twice rules as payouts:

  queued -> submitted (committed BEFORE Daraja is called) -> succeeded | failed | unknown
  unknown is never resent. A confirmed failure is retried as a NEW attempt (up to 5, then a
  person is asked); the customer's money stays reserved for them the whole time.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments import ledger, outbox
from app.payments.adapter import ProviderError
from app.payments.config import get_payments_config
from app.payments.models import CustomerRefund
from app.payments.payouts import MANUAL_REVIEW_AFTER, _urls
from app.payments.provider import get_provider

MAX_ATTEMPTS = 5
RETRY_AFTER = timedelta(minutes=15)


def _shadow() -> bool:
    return get_payments_config().payments_shadow


async def queue_refund(
    session: AsyncSession,
    *,
    order_ref: str,
    phone: str,
    amount: int,
    reason: str,
    attempt: int = 1,
    retry_of: uuid.UUID | None = None,
) -> CustomerRefund | None:
    """A `queued` refund. None = this order already has a live one (unique index), or there is
    no phone to send it to (a person is asked instead)."""
    if not phone:
        return None
    row = CustomerRefund(
        order_ref=order_ref,
        phone=phone,
        amount=amount,
        reason=reason[:300],
        status="queued",
        attempt=attempt,
        retry_of=retry_of,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        return None
    return row


async def apply_result(
    session: AsyncSession, rid: uuid.UUID, code: int, desc: str, transaction_id: str | None
) -> bool:
    r = await session.scalar(
        select(CustomerRefund).where(CustomerRefund.id == rid).with_for_update()
    )
    if r is None or r.status not in ("submitted", "unknown", "manual_review"):
        return False
    ok = code == 0
    r.status = "succeeded" if ok else "failed"
    r.result_code, r.result_desc = code, desc[:300]
    r.transaction_id = transaction_id if ok else None
    r.updated_at = datetime.now(UTC)
    if ok:  # the customer's reserved money has left the Paybill
        await ledger.move(
            session,
            idem_key=f"refund:{r.id}:paid",
            party_type="customer",
            party_id=uuid.UUID(r.order_ref),
            src="reserved",
            dst="paid",
            amount=r.amount,
            kind="refund_paid",
            order_ref=r.order_ref,
            shadow=_shadow(),
        )
    outbox.publish(
        session,
        "refund.succeeded" if ok else "refund.failed",
        {"order_ref": r.order_ref, "amount": r.amount, "attempt": r.attempt},
    )
    await session.flush()
    return True


async def submit(session: AsyncSession, rid: uuid.UUID, provider=None) -> str:
    provider = provider or get_provider()
    now = datetime.now(UTC)
    claimed = await session.execute(
        update(CustomerRefund)
        .where(CustomerRefund.id == rid, CustomerRefund.status == "queued")
        .values(status="submitted", submitted_at=now, updated_at=now)
    )
    if claimed.rowcount != 1:
        return "not_claimed"
    await session.commit()  # before the network call: a crash leaves "submitted", never "queued"
    r = await session.get(CustomerRefund, rid)
    result_url, timeout_url = _urls()
    try:
        accepted = await provider.disburse(
            phone=r.phone,
            amount=r.amount,
            originator_id=str(r.id),
            result_url=result_url,
            timeout_url=timeout_url,
        )
    except ProviderError as e:
        await apply_result(session, rid, -1, f"rejected: {e}", None)
    except Exception as e:  # noqa: BLE001 - we cannot know if it was sent: never resend
        await session.execute(
            update(CustomerRefund)
            .where(CustomerRefund.id == rid, CustomerRefund.status == "submitted")
            .values(status="unknown", result_desc=f"no answer: {type(e).__name__}"[:300])
        )
    else:
        r.conversation_id = accepted.conversation_id
        if accepted.final is not None:
            code = 0 if accepted.final.result_code == 0 else -1
            await apply_result(
                session, rid, code, accepted.final.reason, accepted.final.transaction_id
            )
    await session.commit()
    return (
        await session.scalar(select(CustomerRefund.status).where(CustomerRefund.id == rid))
    ) or "gone"


async def exists(session: AsyncSession, rid: uuid.UUID) -> bool:
    return await session.get(CustomerRefund, rid) is not None


async def apply_callback(session: AsyncSession, rid: uuid.UUID, res: dict, params: dict) -> bool:
    r = await session.get(CustomerRefund, rid)
    if r is None:
        return False
    code = int(res.get("ResultCode", -1))
    if res.get("ConversationID") and r.conversation_id is None:
        r.conversation_id = res["ConversationID"]
    if (
        code == 0
        and "TransactionAmount" in params
        and int(float(params["TransactionAmount"])) != r.amount
    ):
        r.status, r.result_desc = "manual_review", "amount in result differs from the refund"
        return True
    return await apply_result(
        session,
        rid,
        code,
        str(res.get("ResultDesc", "")),
        res.get("TransactionID") if code == 0 else None,
    )


async def mark_unknown(session: AsyncSession, rid: uuid.UUID) -> bool:
    r = await session.execute(
        update(CustomerRefund)
        .where(CustomerRefund.id == rid, CustomerRefund.status == "submitted")
        .values(status="unknown", result_desc="Daraja timed out")
    )
    return r.rowcount == 1


async def process(session: AsyncSession, now: datetime, provider=None) -> int:
    """Every minute: send queued refunds, settle unknown ones, retry failed ones."""
    from app.services import payments as pilot_payments

    provider = provider or get_provider()
    done = 0
    for r in (
        await session.scalars(select(CustomerRefund).where(CustomerRefund.status == "queued"))
    ).all():
        await submit(session, r.id, provider)
        done += 1
    result_url, timeout_url = _urls()
    for r in (
        await session.scalars(select(CustomerRefund).where(CustomerRefund.status == "unknown"))
    ).all():
        try:
            st = await provider.query_disbursement(
                str(r.id), result_url=result_url, timeout_url=timeout_url
            )
        except Exception:  # noqa: BLE001
            st = None
        if st is not None and st.result_code is not None:
            done += await apply_result(
                session, r.id, 0 if st.result_code == 0 else -1, st.reason, st.transaction_id
            )
        elif r.submitted_at and now - r.submitted_at > MANUAL_REVIEW_AFTER:
            r.status, r.result_desc = "manual_review", "no answer after 24 hours"
            done += 1
    # A confirmed failure: try again later as a new attempt; after 5, ask a person.
    failed = (
        await session.scalars(
            select(CustomerRefund).where(
                CustomerRefund.status == "failed", CustomerRefund.updated_at < now - RETRY_AFTER
            )
        )
    ).all()
    for r in failed:
        live = await session.scalar(
            select(func.count())
            .select_from(CustomerRefund)
            .where(CustomerRefund.order_ref == r.order_ref, CustomerRefund.status != "failed")
        )
        if live:
            continue
        if r.attempt >= MAX_ATTEMPTS:
            await _ask_a_person(session, r, pilot_payments)
            continue
        if await queue_refund(
            session,
            order_ref=r.order_ref,
            phone=r.phone,
            amount=r.amount,
            reason=r.reason,
            attempt=r.attempt + 1,
            retry_of=r.id,
        ):
            done += 1
    await session.commit()
    return done


async def _ask_a_person(session: AsyncSession, r: CustomerRefund, pilot_payments) -> None:
    from app.models import Order

    order = await session.get(Order, uuid.UUID(r.order_ref))
    if order is None:
        return
    await pilot_payments.open_review(  # one open item per order and type: a repeat is a no-op
        session,
        type="overpaid",
        hotel_id=order.hotel_id,
        order_id=order.id,
        reason=f"Refund of KES {r.amount:,} to {r.phone} failed {r.attempt} times: pay it by hand",
    )
