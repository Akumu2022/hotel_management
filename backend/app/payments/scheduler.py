"""Scheduled payments jobs. Each is safe to run twice (job_runs + unique payout index) and each
rider is processed on their own, so one failure never blocks the others."""

import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments import ledger, outbox, payouts
from app.payments.config import get_payments_config
from app.payments.models import JobRun, Payout, WalletEntry
from app.payments.provider import get_provider

log = logging.getLogger("app.payments")
NAIROBI = ZoneInfo("Africa/Nairobi")
CUTOFF = time(21, 30)


async def _claim_run(session: AsyncSession, job: str, run_key: str) -> bool:
    res = await session.execute(
        insert(JobRun)
        .values(job=job, run_key=run_key)
        .on_conflict_do_nothing(index_elements=["job", "run_key"])
        .returning(JobRun.id)
    )
    return res.scalar() is not None


async def owed(session: AsyncSession, *, shadow: bool) -> int:
    """Everything the platform holds for others: pending + available + reserved, all parties."""
    q = select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(
        WalletEntry.shadow == shadow, WalletEntry.bucket.in_(("pending", "available", "reserved"))
    )
    return int(await session.scalar(q))


async def float_ok(session: AsyncSession, provider=None) -> tuple[bool, int | None, int]:
    """Does the payout account cover what is owed? If the balance cannot be read, the answer
    is NO (fail closed): nobody is paid on a guess."""
    provider = provider or get_provider()
    due = await owed(session, shadow=get_payments_config().payments_shadow)
    try:
        balance = await provider.account_balance()
    except Exception as e:  # noqa: BLE001
        log.warning("float check could not read the balance: %s", e)
        outbox.publish(session, "float.low", {"reason": "balance unreadable", "owed": due})
        return False, None, due
    ok = balance >= due
    if not ok:
        outbox.publish(session, "float.low", {"balance": balance, "owed": due})
    return ok, balance, due


async def daily_rider_payout(
    session: AsyncSession, now: datetime, payees: dict, provider=None
) -> dict:
    """`payees` maps rider_id -> M-Pesa number for approved, un-held riders (the app layer
    decides who is eligible; this module only pays ids it is given)."""
    cfg = get_payments_config()
    provider = provider or get_provider()
    day = now.astimezone(NAIROBI).date()
    out = {"paid": 0, "skipped": 0, "capped": 0, "blocked": False}
    ok, _, _ = await float_ok(session, provider)
    if not ok:
        out["blocked"] = True  # balances stay available; try again at the next run
        await session.commit()
        return out
    if not await _claim_run(session, "rider_payout", day.isoformat()):
        return {**out, "already_ran": True}
    await session.commit()
    sent_global = int(
        await session.scalar(
            select(func.coalesce(func.sum(Payout.amount + Payout.charge), 0)).where(
                Payout.payout_date == day, Payout.status.in_(payouts.OPEN)
            )
        )
    )
    for rider_id, phone in payees.items():
        try:
            available = await ledger.balance(
                session, "rider", rider_id, "available", shadow=cfg.payments_shadow
            )
            if available < cfg.payout_min:
                out["skipped"] += 1  # rolls over to tomorrow
                continue
            room = cfg.payout_rider_daily_cap - await payouts.paid_today(session, rider_id, day)
            amount = min(available, room)
            if amount < cfg.payout_min:
                out["capped"] += 1
                continue
            if sent_global + amount > cfg.payout_global_daily_cap:
                out["capped"] += 1
                outbox.publish(session, "payout.capped", {"rider_id": str(rider_id)})
                continue
            row = await payouts.queue_payout(
                session, rider_id=rider_id, phone=phone, amount=amount, kind="auto", day=day
            )
            if row is None:
                out["skipped"] += 1  # already paid today (e.g. Withdraw now)
                continue
            await session.commit()
            status = await payouts.submit(session, row.id, provider)
            sent_global += amount
            out["paid" if status in ("succeeded", "submitted", "unknown") else "skipped"] += 1
        except Exception:  # noqa: BLE001 - one rider's failure must not stop the others
            await session.rollback()
            log.exception("payout failed for rider %s", rider_id)
    await session.commit()
    return out


async def run(session: AsyncSession, now: datetime) -> int:
    """Entry point for services/jobs.py (every minute). Does nothing unless payments are on."""
    cfg = get_payments_config()
    if not cfg.payments_enabled:
        return 0
    provider = get_provider()
    n = await payouts.resolve_unknown(session, now, provider)
    await session.commit()
    if now.astimezone(NAIROBI).time() >= CUTOFF:
        from app.payments.hook import eligible_riders

        r = await daily_rider_payout(session, now, await eligible_riders(session), provider)
        n += r.get("paid", 0)
    return n
