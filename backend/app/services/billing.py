"""Weekly statements, hotel payments to the platform, auto-pause, rider payouts.

The money stays where it is paid: customers pay each hotel's Till, so each hotel owes the
platform its commission and service fees (plus rider fees it held for weekly-paid riders), less
what the platform owes it (bonuses it funded, failed-delivery credits). Hotels pay by M-Pesa
Send Money to the platform's number and claim the payment in the app with its code; the super
admin confirms it against their own M-Pesa SMS before it counts.

    balance(hotel) = obligations hotel->platform - obligations platform->hotel
                     - confirmed payments hotel->platform

Weeks are Monday to Sunday, Kenya time. Monday's statement covers the week just ended and is due
`hotel_overdue_days` later. A hotel is paused automatically while a statement is overdue or it
owes more than `hotel_unpaid_limit`, and resumes automatically once that is no longer true
(a pause set by an admin for another reason is never lifted by this).
"""

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Hotel, LedgerEntry, RiderPayout, Settlement, Statement, User
from app.services import events, ledger, settings

EAT = timedelta(hours=3)
UNPAID_PAUSE = "Unpaid Chakula balance"  # pause_reason the billing job owns


def kenya_date(now: datetime) -> date:
    return (now + EAT).date()


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def at_kenya_midnight(d: date) -> datetime:
    return datetime.combine(d, time(), tzinfo=UTC) - EAT


def _signed():
    """+ what the hotel owes the platform, - what the platform owes or received from the hotel."""
    return case(
        (
            (LedgerEntry.kind == "obligation")
            & (LedgerEntry.from_party == "hotel")
            & (LedgerEntry.to_party == "platform"),
            LedgerEntry.amount,
        ),
        (
            (LedgerEntry.kind == "obligation")
            & (LedgerEntry.from_party == "platform")
            & (LedgerEntry.to_party == "hotel"),
            -LedgerEntry.amount,
        ),
        (LedgerEntry.entry_type == "settlement", -LedgerEntry.amount),
        else_=0,
    )


def _hotel_entries(hotel_id: uuid.UUID):
    return (LedgerEntry.from_id == hotel_id) | (LedgerEntry.to_id == hotel_id)


async def hotel_balance(
    session: AsyncSession, hotel_id: uuid.UUID, until: datetime | None = None
) -> int:
    stmt = select(func.coalesce(func.sum(_signed()), 0)).where(_hotel_entries(hotel_id))
    if until is not None:
        stmt = stmt.where(LedgerEntry.created_at < until)
    return int(await session.scalar(stmt))


async def _week_totals(session, hotel_id, start: datetime, end: datetime) -> dict[str, int]:
    rows = (
        await session.execute(
            select(LedgerEntry.entry_type, func.sum(LedgerEntry.amount))
            .where(
                _hotel_entries(hotel_id),
                LedgerEntry.created_at >= start,
                LedgerEntry.created_at < end,
            )
            .group_by(LedgerEntry.entry_type)
        )
    ).all()
    t = {k: int(v) for k, v in rows}
    g = t.get
    return {
        # Charges are the stored per-order amounts; refunds show as credits.
        "commission": g("commission", 0),
        "service_fee": g("service_fee", 0),
        "rider_fees_held": g("rider_fee_held", 0),
        "credits": max(
            g("commission_reversal", 0)
            + g("service_fee_reversal", 0)
            + g("bonus_credit", 0)
            + g("failed_delivery_credit", 0)
            - g("bonus_credit_reversal", 0),
            0,
        ),
        "sales": g("till_received", 0) + g("cash_received", 0) - g("refund", 0),
        "paid": g("settlement", 0),
    }


# --- Statements ----------------------------------------------------------------------------------


async def make_statement(
    session: AsyncSession, hotel: Hotel, week: date, due_days: int
) -> Statement | None:
    """The statement for the week starting `week` (a Monday). Idempotent."""
    existing = await session.scalar(
        select(Statement).where(Statement.hotel_id == hotel.id, Statement.week_start == week)
    )
    if existing is not None:
        return existing
    start, end = at_kenya_midnight(week), at_kenya_midnight(week + timedelta(days=7))
    totals = await _week_totals(session, hotel.id, start, end)
    opening = await hotel_balance(session, hotel.id, until=start)
    closing = await hotel_balance(session, hotel.id, until=end)
    if not any(totals.values()) and opening == 0 and closing == 0:
        return None  # nothing happened and nothing owed: no statement
    statement = Statement(
        hotel_id=hotel.id,
        week_start=week,
        commission_total=totals["commission"],
        service_fee_total=totals["service_fee"],
        rider_fees_held=totals["rider_fees_held"],
        credits_total=totals["credits"],
        opening_balance=opening,
        amount_due=max(closing, 0),
        due_date=week + timedelta(days=7 + due_days),
        status="open" if closing > 0 else "paid",
    )
    try:
        async with session.begin_nested():
            session.add(statement)
            await session.flush()
    except IntegrityError:  # another worker made it first
        return await session.scalar(
            select(Statement).where(Statement.hotel_id == hotel.id, Statement.week_start == week)
        )
    events.emit(session, f"hotel:{hotel.id}", {"type": "statement"})
    return statement


async def paid_since(session: AsyncSession, hotel_id: uuid.UUID, since: datetime) -> int:
    """Confirmed payments from the hotel to the platform since `since`."""
    v = await session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.entry_type == "settlement",
            LedgerEntry.from_id == hotel_id,
            LedgerEntry.created_at >= since,
        )
    )
    return int(v)


def week_end(s: Statement) -> datetime:
    return at_kenya_midnight(s.week_start + timedelta(days=7))


async def left_to_pay(session: AsyncSession, s: Statement) -> int:
    """A statement is paid once payments made after its week cover its amount due. Each
    statement carries the balance forward, so paying the latest one clears all earlier ones."""
    return max(s.amount_due - await paid_since(session, s.hotel_id, week_end(s)), 0)


async def latest_statement(session: AsyncSession, hotel_id: uuid.UUID) -> Statement | None:
    return await session.scalar(
        select(Statement)
        .where(Statement.hotel_id == hotel_id)
        .order_by(Statement.week_start.desc())
        .limit(1)
    )


async def outstanding(session: AsyncSession, hotel_id: uuid.UUID) -> int:
    """What is still owed on statements already issued (this week's activity is not due yet)."""
    last = await latest_statement(session, hotel_id)
    return 0 if last is None else await left_to_pay(session, last)


async def _mark_statements(session: AsyncSession, hotel_id: uuid.UUID, today: date) -> None:
    rows = (
        (
            await session.execute(
                select(Statement).where(Statement.hotel_id == hotel_id, Statement.status != "paid")
            )
        )
        .scalars()
        .all()
    )
    for s in rows:
        if await left_to_pay(session, s) == 0:
            s.status = "paid"
        elif today > s.due_date:
            s.status = "overdue"


async def enforce(session: AsyncSession, hotel: Hotel, now: datetime) -> bool:
    """Pause or resume a hotel for unpaid balances. Returns True when it changed."""
    values, _ = await settings.load(session)
    today = kenya_date(now)
    await _mark_statements(session, hotel.id, today)
    overdue = await session.scalar(
        select(func.count())
        .select_from(Statement)
        .where(Statement.hotel_id == hotel.id, Statement.status == "overdue")
    )
    too_much = await outstanding(session, hotel.id) > values.hotel_unpaid_limit
    should_pause = bool(overdue) or too_much
    if should_pause and hotel.status == "active":
        hotel.status = "paused"
        hotel.pause_reason = UNPAID_PAUSE
    elif not should_pause and hotel.status == "paused" and hotel.pause_reason == UNPAID_PAUSE:
        hotel.status = "active"
        hotel.pause_reason = None
    else:
        return False
    await session.flush()
    payload = {"type": "hotel", "status": hotel.status}
    events.emit(session, f"hotel:{hotel.id}", payload)
    events.emit(session, "admin", {**payload, "hotel": hotel.name})
    return True


async def weekly_job(session: AsyncSession, now: datetime) -> int:
    """Background job: last week's statements (once), statuses, and auto pause / resume."""
    values, _ = await settings.load(session)
    last_week = week_start(kenya_date(now)) - timedelta(days=7)
    changed = 0
    for hotel in (await session.execute(select(Hotel))).scalars().all():
        await make_statement(session, hotel, last_week, values.hotel_overdue_days)
        changed += await enforce(session, hotel, now)
    return changed


# --- Hotel payments to the platform ---------------------------------------------------------


async def claim(
    session: AsyncSession, hotel_id: uuid.UUID, *, code: str, amount: int, user_id: uuid.UUID
) -> Settlement:
    """The hotel says it sent `amount` with M-Pesa code `code` to the platform's number."""
    code = code.strip().upper()
    if amount <= 0:
        raise AppError(422, "bad_amount", "Enter the amount you sent")
    existing = await session.scalar(
        select(Settlement).where(Settlement.mpesa_code == code).with_for_update()
    )
    if existing is not None:
        if existing.hotel_id != hotel_id:
            raise AppError(409, "code_used", "That M-Pesa code was already used")
        if existing.status == "rejected":  # corrected and sent again
            existing.status, existing.amount, existing.note = "pending", amount, None
            existing.claimed_by = user_id
            await session.flush()
            _settlement_event(session, hotel_id)
        return existing  # or a repeat tap
    s = Settlement(
        hotel_id=hotel_id, amount=amount, mpesa_code=code, status="pending", claimed_by=user_id
    )
    try:
        async with session.begin_nested():
            session.add(s)
            await session.flush()
    except IntegrityError:  # the same code claimed at the same moment
        raise AppError(409, "code_used", "That M-Pesa code was already used") from None
    _settlement_event(session, hotel_id)
    return s


def _settlement_event(session: AsyncSession, hotel_id: uuid.UUID) -> None:
    """Pending claims ring the super admin until confirmed or rejected."""
    events.emit(session, "admin", {"type": "settlement", "hotel_id": str(hotel_id)})
    events.emit(session, f"hotel:{hotel_id}", {"type": "settlement"})


async def confirm(
    session: AsyncSession,
    settlement_id: uuid.UUID,
    admin_id: uuid.UUID,
    now: datetime,
    *,
    amount: int | None = None,
) -> Settlement:
    """The money is on the platform's M-Pesa: it counts now. `amount` corrects a typo in the
    hotel's claim to what the SMS actually shows."""
    s = await session.get(Settlement, settlement_id, with_for_update=True)
    if s is None:
        raise AppError(404, "not_found", "Payment not found")
    if s.status == "confirmed":
        return s
    if s.status != "pending":
        raise AppError(409, "not_pending", "This payment was already marked not received")
    if amount is not None:
        if amount <= 0:
            raise AppError(422, "bad_amount", "Enter the amount on the M-Pesa message")
        s.amount = amount
    s.status = "confirmed"
    s.confirmed_at = now
    s.recorded_by = admin_id
    await session.flush()
    await ledger._write(
        session,
        "settlement",
        s.amount,
        from_id=s.hotel_id,
        settlement_id=s.id,
        reference=s.mpesa_code,
        created_by=admin_id,
        at=now,
    )
    hotel = await session.get(Hotel, s.hotel_id, with_for_update=True)
    await enforce(session, hotel, now)  # may lift an unpaid pause straight away
    _settlement_event(session, s.hotel_id)
    return s


async def reject(
    session: AsyncSession, settlement_id: uuid.UUID, note: str, admin_id: uuid.UUID
) -> Settlement:
    s = await session.get(Settlement, settlement_id, with_for_update=True)
    if s is None:
        raise AppError(404, "not_found", "Payment not found")
    if s.status == "rejected":
        return s
    if s.status != "pending":
        raise AppError(409, "not_pending", "This payment was already confirmed")
    if not note.strip():
        raise AppError(422, "reason_required", "Tell the hotel why")
    s.status = "rejected"
    s.note = note.strip()[:200]
    s.recorded_by = admin_id
    await session.flush()
    _settlement_event(session, s.hotel_id)
    return s


# --- Rider payouts ---------------------------------------------------------------------------


def _rider_signed():
    """+ what the platform owes the rider, - what it has paid them."""
    return case(
        (
            (LedgerEntry.kind == "obligation")
            & (LedgerEntry.from_party == "platform")
            & (LedgerEntry.to_party == "rider"),
            LedgerEntry.amount,
        ),
        (LedgerEntry.entry_type == "rider_payout", -LedgerEntry.amount),
        else_=0,
    )


async def rider_balances(session: AsyncSession) -> dict[uuid.UUID, int]:
    rows = (
        await session.execute(
            select(LedgerEntry.to_id, func.sum(_rider_signed()))
            .where(LedgerEntry.to_party == "rider")
            .group_by(LedgerEntry.to_id)
        )
    ).all()
    return {rid: int(v) for rid, v in rows if rid is not None}


async def rider_balance(session: AsyncSession, rider_id: uuid.UUID) -> int:
    v = await session.scalar(
        select(func.coalesce(func.sum(_rider_signed()), 0)).where(LedgerEntry.to_id == rider_id)
    )
    return int(v)


async def pay_rider(
    session: AsyncSession,
    rider_id: uuid.UUID,
    *,
    amount: int,
    code: str,
    admin_id: uuid.UUID,
    now: datetime,
) -> RiderPayout:
    """The platform sent a rider what it owed them (weekly-paid fees, compensations)."""
    rider = await session.get(User, rider_id, with_for_update=True)  # one payout at a time
    if rider is None or rider.role != "rider":
        raise AppError(404, "not_found", "Rider not found")
    code = code.strip().upper()
    existing = await session.scalar(select(RiderPayout).where(RiderPayout.mpesa_code == code))
    if existing is not None:
        if existing.rider_id == rider_id and existing.amount == amount:
            return existing  # repeat tap
        raise AppError(409, "code_used", "That M-Pesa code was already used")
    owed = await rider_balance(session, rider_id)
    if amount <= 0 or amount > owed:
        raise AppError(422, "bad_amount", f"The platform owes this rider KES {owed:,}")
    payout = RiderPayout(
        rider_id=rider_id,
        period_start=week_start(kenya_date(now)),
        amount=amount,
        mpesa_code=code,
        paid_at=now,
        recorded_by=admin_id,
    )
    try:
        async with session.begin_nested():
            session.add(payout)
            await session.flush()
    except IntegrityError:
        raise AppError(409, "code_used", "That M-Pesa code was already used") from None
    await ledger._write(
        session,
        "rider_payout",
        amount,
        to_id=rider_id,
        payout_id=payout.id,
        reference=code,
        created_by=admin_id,
        at=now,
    )
    events.emit(session, "admin", {"type": "payout"})
    events.emit(session, "riders", {"type": "payout", "rider_id": str(rider_id)})
    return payout


# --- Views -------------------------------------------------------------------------------------


async def statement_out(session: AsyncSession, s: Statement) -> dict:
    start, end = at_kenya_midnight(s.week_start), week_end(s)
    totals = await _week_totals(session, s.hotel_id, start, end)
    return {
        "id": str(s.id),
        "week_start": s.week_start,
        "week_end": s.week_start + timedelta(days=6),
        "sales": totals["sales"],
        "commission": s.commission_total,
        "service_fees": s.service_fee_total,
        "rider_fees_held": s.rider_fees_held,
        "credits": s.credits_total,
        "opening_balance": s.opening_balance,
        "paid_during_week": totals["paid"],
        "amount_due": s.amount_due,
        "left_to_pay": await left_to_pay(session, s),
        "due_date": s.due_date,
        "status": s.status,
    }


def settlement_out(s: Settlement, hotel_name: str | None = None) -> dict:
    return {
        "id": str(s.id),
        "hotel_id": str(s.hotel_id),
        "hotel_name": hotel_name,
        "amount": s.amount,
        "mpesa_code": s.mpesa_code,
        "status": s.status,
        "note": s.note,
        "created_at": s.created_at,
        "confirmed_at": s.confirmed_at,
    }


async def hotel_view(session: AsyncSession, hotel: Hotel, now: datetime) -> dict:
    """Everything a hotel needs to pay: what's due, by when, where to send it, and history."""
    values, _ = await settings.load(session)
    this_week = at_kenya_midnight(week_start(kenya_date(now)))
    statements = (
        (
            await session.execute(
                select(Statement)
                .where(Statement.hotel_id == hotel.id)
                .order_by(Statement.week_start.desc())
                .limit(26)
            )
        )
        .scalars()
        .all()
    )
    settlements = (
        (
            await session.execute(
                select(Settlement)
                .where(Settlement.hotel_id == hotel.id)
                .order_by(Settlement.created_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    latest = statements[0] if statements else None
    due = await left_to_pay(session, latest) if latest else 0
    return {
        "hotel_id": str(hotel.id),
        "hotel_name": hotel.name,
        "pay_to": values.platform_mpesa_number,
        "due_now": due,
        "due_date": latest.due_date if latest and due else None,
        "overdue": bool(latest and due and kenya_date(now) > latest.due_date),
        "balance": await hotel_balance(session, hotel.id),
        "this_week": await _week_totals(session, hotel.id, this_week, now),
        "pending_claims": sum(s.amount for s in settlements if s.status == "pending"),
        "unpaid_limit": values.hotel_unpaid_limit,
        "paused_for_billing": hotel.status == "paused" and hotel.pause_reason == UNPAID_PAUSE,
        "statements": [await statement_out(session, s) for s in statements],
        "payments": [settlement_out(s) for s in settlements],
    }


async def admin_overview(session: AsyncSession, now: datetime) -> dict:
    hotels = (await session.execute(select(Hotel).order_by(Hotel.name))).scalars().all()
    names = {h.id: h.name for h in hotels}
    rows = []
    for h in hotels:
        latest = await latest_statement(session, h.id)
        due = await left_to_pay(session, latest) if latest else 0
        rows.append(
            {
                "hotel_id": str(h.id),
                "hotel_name": h.name,
                "status": h.status,
                "pause_reason": h.pause_reason,
                "due_now": due,
                "due_date": latest.due_date if latest and due else None,
                "overdue": bool(latest and due and kenya_date(now) > latest.due_date),
                "balance": await hotel_balance(session, h.id),
            }
        )
    pending = (
        (
            await session.execute(
                select(Settlement)
                .where(Settlement.status == "pending")
                .order_by(Settlement.created_at)
            )
        )
        .scalars()
        .all()
    )
    recent = (
        (
            await session.execute(
                select(Settlement)
                .where(Settlement.status != "pending")
                .order_by(Settlement.created_at.desc())
                .limit(30)
            )
        )
        .scalars()
        .all()
    )
    values, _ = await settings.load(session)
    return {
        "pay_to": values.platform_mpesa_number,
        "total_due": sum(r["due_now"] for r in rows),
        "hotels": rows,
        "pending": [settlement_out(s, names.get(s.hotel_id)) for s in pending],
        "recent": [settlement_out(s, names.get(s.hotel_id)) for s in recent],
    }


async def pending_count(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(Settlement).where(Settlement.status == "pending")
        )
    )


def payout_out(p: RiderPayout) -> dict:
    return {"id": str(p.id), "amount": p.amount, "mpesa_code": p.mpesa_code, "paid_at": p.paid_at}


async def riders_overview(session: AsyncSession) -> list[dict]:
    """Every rider the platform owes money or has paid, most owed first."""
    owed = await rider_balances(session)
    paid_ids = set((await session.execute(select(RiderPayout.rider_id).distinct())).scalars().all())
    ids = {rid for rid, v in owed.items() if v} | paid_ids
    if not ids:
        return []
    users = (await session.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    out = []
    for u in users:
        last = await session.scalar(
            select(RiderPayout)
            .where(RiderPayout.rider_id == u.id)
            .order_by(RiderPayout.paid_at.desc())
            .limit(1)
        )
        out.append(
            {
                "rider_id": str(u.id),
                "name": u.name,
                "phone": u.phone,
                "owed": owed.get(u.id, 0),
                "last_payout": payout_out(last) if last else None,
            }
        )
    out.sort(key=lambda r: (-r["owed"], r["name"]))
    return out


async def rider_view(session: AsyncSession, rider_id: uuid.UUID) -> dict:
    payouts = (
        (
            await session.execute(
                select(RiderPayout)
                .where(RiderPayout.rider_id == rider_id)
                .order_by(RiderPayout.paid_at.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    return {
        "owed": await rider_balance(session, rider_id),
        "payouts": [payout_out(p) for p in payouts],
    }
