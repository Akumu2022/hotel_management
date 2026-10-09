"""Hotel daily settlement: one payment per hotel per day for what the hotel earned on delivered
(or handed-over) orders, listed order by order. Same never-twice rules as rider payouts:

  queued -> submitted (committed BEFORE Daraja is called) -> succeeded | failed | unknown
  unknown is never resent; a confirmed failure returns the money and the next day pays it again.
"""

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments import ledger, outbox
from app.payments.adapter import ProviderError
from app.payments.config import get_payments_config
from app.payments.models import HotelSettlement, WalletEntry
from app.payments.payouts import MANUAL_REVIEW_AFTER, _urls
from app.payments.provider import get_provider


def _shadow() -> bool:
    return get_payments_config().payments_shadow


async def statement_for(
    session: AsyncSession, hotel_id: uuid.UUID, cutoff: datetime, cap: int
) -> list[dict]:
    """The orders a hotel can be paid for now: hotel-share credits made before `cutoff` that are
    not in an earlier settlement, oldest first, up to `cap` KES in total."""
    taken: set[str] = set()
    for detail in await session.scalars(
        select(HotelSettlement.detail).where(
            HotelSettlement.hotel_id == hotel_id, HotelSettlement.status != "failed"
        )
    ):
        taken.update(i["order_ref"] for i in detail or [])
    rows = await session.scalars(
        select(WalletEntry)
        .where(
            WalletEntry.party_type == "hotel",
            WalletEntry.party_id == hotel_id,
            WalletEntry.bucket == "available",
            WalletEntry.kind == "hotel_share_credit",
            WalletEntry.shadow == _shadow(),
            WalletEntry.created_at < cutoff,
        )
        .order_by(WalletEntry.created_at)
    )
    items, total = [], 0
    for r in rows:
        if r.order_ref in taken:
            continue
        if total + r.amount > cap:
            break
        items.append({"order_ref": r.order_ref, "amount": r.amount})
        total += r.amount
    return items


async def queue_settlement(
    session: AsyncSession,
    *,
    hotel_id: uuid.UUID,
    day: date,
    channel: str,
    destination: str,
    items: list[dict],
) -> HotelSettlement | None:
    """available -> reserved and a `queued` row, atomically. None = this hotel already has the
    day's settlement (unique index), so a repeated job run changes nothing."""
    amount = sum(i["amount"] for i in items)
    row = HotelSettlement(
        hotel_id=hotel_id,
        statement_date=day,
        channel=channel,
        destination=destination,
        amount=amount,
        status="queued",
        detail=items,
    )
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
            await ledger.move(
                session,
                idem_key=f"settlement:{row.id}:reserve",
                party_type="hotel",
                party_id=hotel_id,
                src="available",
                dst="reserved",
                amount=amount,
                kind="settlement_reserved",
                order_ref=None,
                shadow=_shadow(),
            )
    except IntegrityError:
        return None
    return row


async def apply_result(
    session: AsyncSession, sid: uuid.UUID, code: int, reason: str, transaction_id: str | None
) -> bool:
    s = await session.scalar(
        select(HotelSettlement).where(HotelSettlement.id == sid).with_for_update()
    )
    if s is None or s.status not in ("submitted", "unknown", "manual_review"):
        return False
    ok = code == 0
    s.status = "succeeded" if ok else "failed"
    s.result_code, s.reason = code, reason[:300]
    s.transaction_id = transaction_id if ok else None
    s.updated_at = datetime.now(UTC)
    await ledger.move(
        session,
        idem_key=f"settlement:{s.id}:{'paid' if ok else 'fail'}",
        party_type="hotel",
        party_id=s.hotel_id,
        src="reserved",
        dst="paid" if ok else "available",
        amount=s.amount,
        kind="settlement_paid" if ok else "settlement_returned",
        order_ref=None,
        shadow=_shadow(),
    )
    outbox.publish(
        session,
        "settlement.succeeded" if ok else "settlement.failed",
        {"settlement_id": str(s.id), "hotel_id": str(s.hotel_id), "amount": s.amount},
    )
    await session.flush()
    return True


async def submit(session: AsyncSession, sid: uuid.UUID, provider=None) -> str:
    provider = provider or get_provider()
    now = datetime.now(UTC)
    claimed = await session.execute(
        update(HotelSettlement)
        .where(HotelSettlement.id == sid, HotelSettlement.status == "queued")
        .values(status="submitted", submitted_at=now, updated_at=now)
    )
    if claimed.rowcount != 1:
        return "not_claimed"
    await session.commit()  # before the network call: a crash leaves "submitted", never "queued"
    s = await session.get(HotelSettlement, sid)
    result_url, timeout_url = _urls()
    try:
        if s.channel == "till":
            accepted = await provider.pay_till(
                till=s.destination,
                amount=s.amount,
                originator_id=str(s.id),
                result_url=result_url,
                timeout_url=timeout_url,
            )
        else:
            accepted = await provider.disburse(
                phone=s.destination,
                amount=s.amount,
                originator_id=str(s.id),
                result_url=result_url,
                timeout_url=timeout_url,
            )
    except ProviderError as e:
        await apply_result(session, sid, -1, f"rejected: {e}", None)
    except Exception as e:  # noqa: BLE001 - we cannot know if it was sent: never resend
        await session.execute(
            update(HotelSettlement)
            .where(HotelSettlement.id == sid, HotelSettlement.status == "submitted")
            .values(status="unknown", reason=f"no answer: {type(e).__name__}"[:300])
        )
    else:
        s.conversation_id = accepted.conversation_id
        if accepted.final is not None:
            code = 0 if accepted.final.result_code == 0 else -1
            await apply_result(
                session, sid, code, accepted.final.reason, accepted.final.transaction_id
            )
    await session.commit()
    return (
        await session.scalar(select(HotelSettlement.status).where(HotelSettlement.id == sid))
    ) or "gone"


async def apply_callback(session: AsyncSession, sid: uuid.UUID, res: dict, params: dict) -> bool:
    """A Daraja result for a settlement (called by payouts.handle_result when the id is not a
    rider payout)."""
    s = await session.get(HotelSettlement, sid)
    if s is None:
        return False
    code = int(res.get("ResultCode", -1))
    if res.get("ConversationID") and s.conversation_id is None:
        s.conversation_id = res["ConversationID"]
    if (
        code == 0
        and "TransactionAmount" in params
        and int(float(params["TransactionAmount"])) != s.amount
    ):
        s.status, s.reason = "manual_review", "amount in result differs from the settlement"
        return True
    return await apply_result(
        session,
        sid,
        code,
        str(res.get("ResultDesc", "")),
        res.get("TransactionID") if code == 0 else None,
    )


async def mark_unknown(session: AsyncSession, sid: uuid.UUID) -> bool:
    r = await session.execute(
        update(HotelSettlement)
        .where(HotelSettlement.id == sid, HotelSettlement.status == "submitted")
        .values(status="unknown", reason="Daraja timed out")
    )
    return r.rowcount == 1


async def resolve_unknown(session: AsyncSession, now: datetime, provider=None) -> int:
    provider = provider or get_provider()
    result_url, timeout_url = _urls()
    done = 0
    for s in (
        await session.scalars(select(HotelSettlement).where(HotelSettlement.status == "unknown"))
    ).all():
        try:
            st = await provider.query_disbursement(
                str(s.id), result_url=result_url, timeout_url=timeout_url
            )
        except Exception:  # noqa: BLE001
            st = None
        if st is not None and st.result_code is not None:
            done += await apply_result(
                session, s.id, 0 if st.result_code == 0 else -1, st.reason, st.transaction_id
            )
        elif s.submitted_at and now - s.submitted_at > MANUAL_REVIEW_AFTER:
            s.status, s.reason = "manual_review", "no answer after 24 hours"
            outbox.publish(session, "settlement.review", {"settlement_id": str(s.id)})
            done += 1
    await session.flush()
    return done
