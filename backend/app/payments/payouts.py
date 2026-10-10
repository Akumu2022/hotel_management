"""B2C payouts to riders, built around one rule: a payout is never sent twice.

  queued -> submitted (claimed by exactly one worker, COMMITTED before Daraja is called)
  submitted -> succeeded | failed (callback or status query)
  submitted -> unknown (timeout / network error): NEVER resent. Only a confirmed failure frees
  the money again, and a retry is then a NEW row, so the same row can never pay twice.

Money moves between the rider's buckets in the same transaction as each status change:
available -> reserved when queued, reserved -> paid on success, reserved -> available on failure.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments import ledger, outbox
from app.payments.adapter import DisburseStatus, ProviderError
from app.payments.config import get_payments_config
from app.payments.models import Payout
from app.payments.provider import get_provider

OPEN = (
    "queued",
    "submitted",
    "unknown",
    "manual_review",
    "succeeded",
)  # counts toward "paid today"
MANUAL_REVIEW_AFTER = timedelta(hours=24)
WITHDRAW_COOLDOWN = timedelta(seconds=60)


class PayoutError(Exception):
    """Refused for a reason the rider can be told (code + plain message)."""

    def __init__(self, code: str, message: str, **extra):
        super().__init__(message)
        self.code, self.message, self.extra = code, message, extra


def _urls() -> tuple[str, str]:
    cfg = get_payments_config()
    base = (
        f"{cfg.daraja_callback_base.rstrip('/')}/api/v1/payments/daraja/{cfg.daraja_callback_token}"
    )
    return f"{base}/b2c/result", f"{base}/b2c/timeout"


def _shadow() -> bool:
    return get_payments_config().payments_shadow


async def paid_today(session: AsyncSession, rider_id: uuid.UUID, day: date) -> int:
    """KES already sent or on its way to this rider today (amount + charge)."""
    q = select(func.coalesce(func.sum(Payout.amount + Payout.charge), 0)).where(
        Payout.rider_id == rider_id, Payout.payout_date == day, Payout.status.in_(OPEN)
    )
    return int(await session.scalar(q))


async def queue_payout(
    session: AsyncSession,
    *,
    rider_id: uuid.UUID,
    phone: str,
    amount: int,
    charge: int = 0,
    kind: str,
    day: date,
    idem_key: str | None = None,
    retry_of: uuid.UUID | None = None,
) -> Payout | None:
    """available -> reserved and a `queued` row, atomically. None = this rider already has the
    day's payout (the unique index), so a repeated job run changes nothing."""
    row = Payout(
        rider_id=rider_id,
        kind=kind,
        payout_date=day,
        phone=phone,
        amount=amount,
        charge=charge,
        status="queued",
        idem_key=idem_key,
        retry_of=retry_of,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
            await ledger.move(
                session,
                idem_key=f"payout:{row.id}:reserve",
                party_type="rider",
                party_id=rider_id,
                src="available",
                dst="reserved",
                amount=amount + charge,
                kind="payout_reserved",
                order_ref=None,
                shadow=_shadow(),
            )
    except IntegrityError:
        return None
    return row


async def _apply_result(
    session: AsyncSession, payout_id: uuid.UUID, code: int, reason: str, transaction_id: str | None
) -> bool:
    """Finish a payout exactly once. Only a payout still in flight can be finished."""
    p = await session.scalar(select(Payout).where(Payout.id == payout_id).with_for_update())
    if p is None or p.status not in ("submitted", "unknown", "manual_review"):
        return False
    ok = code == 0
    p.status = "succeeded" if ok else "failed"
    p.result_code, p.reason = code, reason[:300]
    p.transaction_id = transaction_id if ok else None
    p.updated_at = datetime.now(UTC)
    await ledger.move(
        session,
        idem_key=f"payout:{p.id}:{'paid' if ok else 'fail'}",
        party_type="rider",
        party_id=p.rider_id,
        src="reserved",
        dst="paid" if ok else "available",
        amount=p.amount + p.charge,
        kind="payout_paid" if ok else "payout_returned",
        order_ref=None,
        shadow=_shadow(),
    )
    outbox.publish(
        session,
        "payout.succeeded" if ok else "payout.failed",
        {"payout_id": str(p.id), "rider_id": str(p.rider_id), "amount": p.amount, "reason": reason},
    )
    await session.flush()
    return True


async def submit(session: AsyncSession, payout_id: uuid.UUID, provider=None) -> str:
    """Send one queued payout. Returns the payout's status afterwards."""
    provider = provider or get_provider()
    now = datetime.now(UTC)
    claimed = await session.execute(
        update(Payout)
        .where(Payout.id == payout_id, Payout.status == "queued")
        .values(status="submitted", submitted_at=now, updated_at=now)
    )
    if claimed.rowcount != 1:
        return "not_claimed"  # another worker owns it, or it is already done
    # Committed BEFORE the network call: if we crash mid-call the row says "submitted"
    # (money possibly sent), never "queued" (which would invite a resend).
    await session.commit()
    p = await session.get(Payout, payout_id)
    result_url, timeout_url = _urls()
    try:
        accepted = await provider.disburse(
            phone=p.phone,
            amount=p.amount,
            originator_id=str(p.id),
            result_url=result_url,
            timeout_url=timeout_url,
        )
    except ProviderError as e:  # clearly rejected: nothing was sent
        await _apply_result(session, payout_id, -1, f"rejected: {e}", None)
    except Exception as e:  # noqa: BLE001 - network/timeout: we cannot know. Never resend.
        await session.execute(
            update(Payout)
            .where(Payout.id == payout_id, Payout.status == "submitted")
            .values(status="unknown", reason=f"no answer: {type(e).__name__}"[:300])
        )
    else:
        p.conversation_id = accepted.conversation_id
        if accepted.final is not None:
            code = accepted.final.result_code
            await _apply_result(
                session,
                payout_id,
                0 if code == 0 else -1,
                accepted.final.reason,
                accepted.final.transaction_id,
            )
    await session.commit()
    return (await session.scalar(select(Payout.status).where(Payout.id == payout_id))) or "gone"


async def handle_result(session: AsyncSession, body: dict) -> bool:
    """Daraja's B2C result (or a Transaction Status result) for a payout."""
    from app.payments.collection import store_callback

    res = body.get("Result", {})
    originator = res.get("OriginatorConversationID")
    if not originator:
        return False
    if not await store_callback(session, "b2c", f"{originator}:{res.get('ResultType', '')}", body):
        return False
    try:
        payout_id = uuid.UUID(originator)
    except ValueError:
        return False
    params = {
        i.get("Key"): i.get("Value")
        for i in res.get("ResultParameters", {}).get("ResultParameter", [])
    }
    code = int(res.get("ResultCode", -1))
    p = await session.get(Payout, payout_id)
    if p is None:  # not a rider payout: a hotel settlement or a customer refund
        from app.payments import refunds, settlements

        if await settlements.exists(session, payout_id):
            return await settlements.apply_callback(session, payout_id, res, params)
        return await refunds.apply_callback(session, payout_id, res, params)
    if p.conversation_id is None and res.get("ConversationID"):
        p.conversation_id = res["ConversationID"]
    if (
        code == 0
        and "TransactionAmount" in params
        and int(float(params["TransactionAmount"])) != p.amount
    ):
        # Paid a different amount than we asked for: a person must look. Funds stay reserved.
        p.status, p.reason = "manual_review", "amount in result differs from the payout"
        return True
    return await _apply_result(
        session,
        payout_id,
        code,
        str(res.get("ResultDesc", "")),
        res.get("TransactionID") if code == 0 else None,
    )


async def handle_status_result(session: AsyncSession, body: dict) -> bool:
    """Transaction Status answer for a payout of unknown outcome. The query's own ResultCode only
    says the QUERY worked; the payout's fate is in TransactionStatus. Anything unclear is left
    alone (still unknown, asked again next run, then manual review after 24 hours)."""
    from app.payments.collection import store_callback

    res = body.get("Result", body)
    params = {
        i.get("Key"): i.get("Value")
        for i in res.get("ResultParameters", {}).get("ResultParameter", [])
    }
    refs = {
        i.get("Key"): i.get("Value")
        for i in (res.get("ReferenceData", {}) or {}).get("ReferenceItem", [])
        if isinstance(i, dict)
    }
    originator = refs.get("Occasion") or params.get("OriginatorConversationID")
    try:
        payout_id = uuid.UUID(str(originator))
    except ValueError:
        return False
    key = f"{res.get('OriginatorConversationID', originator)}:{res.get('ResultCode', '')}"
    if not await store_callback(session, "b2c_status", key, body):
        return False
    if int(res.get("ResultCode", -1)) != 0:
        return False
    status = str(params.get("TransactionStatus", "")).lower()
    if status not in ("completed", "failed"):
        return False
    code = 0 if status == "completed" else -1
    txn = str(params.get("ReceiptNo") or "") or None
    reason = str(params.get("ReasonType") or res.get("ResultDesc", ""))
    if await session.get(Payout, payout_id) is not None:
        return await _apply_result(session, payout_id, code, reason, txn if code == 0 else None)
    from app.payments import refunds, settlements

    if await settlements.exists(session, payout_id):
        return await settlements.apply_callback(
            session, payout_id, {"ResultCode": code, "ResultDesc": reason, "TransactionID": txn}, params
        )
    return await refunds.apply_callback(
        session, payout_id, {"ResultCode": code, "ResultDesc": reason, "TransactionID": txn}, params
    )


async def handle_timeout(session: AsyncSession, body: dict) -> bool:
    """Daraja gave up waiting: we do not know the outcome. Mark unknown, resolve by query."""
    res = body.get("Result", body)
    originator = res.get("OriginatorConversationID")
    try:
        payout_id = uuid.UUID(originator)
    except (TypeError, ValueError):
        return False
    r = await session.execute(
        update(Payout)
        .where(Payout.id == payout_id, Payout.status == "submitted")
        .values(status="unknown", reason="Daraja timed out")
    )
    if r.rowcount == 1:
        return True
    from app.payments import refunds, settlements

    return await settlements.mark_unknown(session, payout_id) or await refunds.mark_unknown(
        session, payout_id
    )


async def resolve_unknown(session: AsyncSession, now: datetime, provider=None) -> int:
    """Ask Daraja about every payout of unknown outcome. Never resends. After 24 hours with no
    answer it goes to manual review (compare with the M-Pesa statement)."""
    provider = provider or get_provider()
    rows = (
        await session.scalars(
            select(Payout).where(Payout.status == "unknown").order_by(Payout.created_at)
        )
    ).all()
    result_url, timeout_url = _urls()
    done = 0
    for p in rows:
        try:
            st: DisburseStatus | None = await provider.query_disbursement(
                str(p.id), result_url=result_url, timeout_url=timeout_url
            )
        except Exception:  # noqa: BLE001 - try again next run
            st = None
        if st is not None and st.result_code is not None:
            code = 0 if st.result_code == 0 else -1
            done += await _apply_result(session, p.id, code, st.reason, st.transaction_id)
        elif p.submitted_at and now - p.submitted_at > MANUAL_REVIEW_AFTER:
            p.status, p.reason = "manual_review", "no answer after 24 hours"
            outbox.publish(session, "payout.review", {"payout_id": str(p.id)})
            done += 1
    await session.flush()
    return done


async def request_withdrawal(
    session: AsyncSession,
    rider_id: uuid.UUID,
    *,
    phone: str,
    idem_key: str,
    accept_charge: bool,
    now: datetime,
    provider=None,
) -> Payout:
    """ "Withdraw now". The first one each day is free and replaces that day's automatic payout;
    later ones have the extra charge taken from the amount (the rider must accept it first)."""
    cfg = get_payments_config()
    existing = await session.scalar(select(Payout).where(Payout.idem_key == idem_key))
    if existing is not None:
        return existing  # the same tap, sent twice
    day = _nairobi_day(now)
    await ledger.lock_party(session, "rider", rider_id)
    recent = await session.scalar(
        select(func.count())
        .select_from(Payout)
        .where(Payout.rider_id == rider_id, Payout.created_at > now - WITHDRAW_COOLDOWN)
    )
    if recent:
        raise PayoutError("too_fast", "Please wait a minute before another withdrawal.")
    available = await ledger.balance(session, "rider", rider_id, "available", shadow=_shadow())
    if available < cfg.payout_min:
        raise PayoutError("below_minimum", f"You need at least KES {cfg.payout_min} to withdraw.")
    already = await session.scalar(
        select(func.count())
        .select_from(Payout)
        .where(Payout.rider_id == rider_id, Payout.payout_date == day, Payout.status.in_(OPEN))
    )
    charge = cfg.payout_extra_charge if already else 0
    if charge and not accept_charge:
        raise PayoutError(
            "charge_needed",
            f"A second withdrawal today costs KES {charge}.",
            charge=charge,
            you_get=max(available - charge, 0),
        )
    sent_today = await paid_today(session, rider_id, day)
    room = cfg.payout_rider_daily_cap - sent_today
    amount = min(available, room) - charge
    if amount < cfg.payout_min:
        raise PayoutError("limit", "You have reached today's withdrawal limit.")
    p = await queue_payout(
        session,
        rider_id=rider_id,
        phone=phone,
        amount=amount,
        charge=charge,
        kind="withdraw_extra" if charge else "withdraw",
        day=day,
        idem_key=idem_key,
    )
    if p is None:
        raise PayoutError("already_today", "Today's free payout is already on its way.")
    await session.commit()
    await submit(session, p.id, provider)
    return await session.get(Payout, p.id)


def _nairobi_day(now: datetime) -> date:
    from zoneinfo import ZoneInfo

    return now.astimezone(ZoneInfo("Africa/Nairobi")).date()
