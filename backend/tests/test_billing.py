"""M7: weekly statements, hotel payments to the platform, auto pause / resume, rider payouts."""

from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.errors import AppError
from app.core.time import utcnow
from app.models import Statement
from app.services import billing, ledger, settings
from tests.factories import auth_header, make_hotel, make_order, make_user


def next_monday_10am(now):
    """10:00 Kenya time on the Monday after `now` (the first day the week's statement exists)."""
    week = billing.week_start(billing.kenya_date(now)) + timedelta(days=7)
    return billing.at_kenya_midnight(week) + timedelta(hours=10)


async def hotel_with_sale(db, food: int = 650):
    """A paid order this week: commission 10% of food, service fee 20."""
    hotel = await make_hotel(db)
    order = await make_order(db, hotel, food=food)
    await ledger.record_payment(db, order, amount=order.till_amount, reference="TJ1")
    return hotel, order


async def statements(db, hotel):
    return (
        (await db.execute(select(Statement).where(Statement.hotel_id == hotel.id))).scalars().all()
    )


async def test_week_dates_are_kenya_time():
    from datetime import UTC, date, datetime

    # Sunday 22:30 UTC is already Monday 01:30 in Nairobi.
    sunday_night = datetime(2026, 10, 4, 22, 30, tzinfo=UTC)
    assert billing.kenya_date(sunday_night) == date(2026, 10, 5)
    assert billing.week_start(date(2026, 10, 4)) == date(2026, 9, 28)
    assert billing.at_kenya_midnight(date(2026, 10, 5)) == datetime(2026, 10, 4, 21, 0, tzinfo=UTC)


async def test_statement_for_last_week(db):
    hotel, _ = await hotel_with_sale(db)
    monday = next_monday_10am(utcnow())
    await billing.weekly_job(db, monday)
    await billing.weekly_job(db, monday + timedelta(minutes=1))  # runs every minute: once only
    [s] = await statements(db, hotel)
    assert (s.commission_total, s.service_fee_total, s.credits_total) == (65, 20, 0)
    assert s.amount_due == 85 and s.opening_balance == 0 and s.status == "open"
    assert s.due_date == billing.kenya_date(monday) + timedelta(days=3)
    out = await billing.statement_out(db, s)
    assert out["sales"] == 770 and out["left_to_pay"] == 85
    await db.refresh(hotel)
    assert hotel.status == "active"  # not due yet


async def test_no_statement_for_a_quiet_week(db):
    hotel = await make_hotel(db)
    await billing.weekly_job(db, next_monday_10am(utcnow()))
    assert await statements(db, hotel) == []


async def test_this_weeks_sales_are_not_due_yet(db):
    hotel, _ = await hotel_with_sale(db)
    view = await billing.hotel_view(db, hotel, utcnow())
    assert view["due_now"] == 0 and view["balance"] == 85
    assert view["this_week"]["commission"] == 65
    assert view["pay_to"] == "254742554713"


async def test_overdue_pauses_and_confirmed_payment_resumes(db):
    hotel, _ = await hotel_with_sale(db)
    admin = await make_user(db, "super_admin")
    owner = await make_user(db, "hotel_admin", hotel)
    monday = next_monday_10am(utcnow())
    await billing.weekly_job(db, monday)

    friday = monday + timedelta(days=4)  # due Thursday
    assert await billing.weekly_job(db, friday) >= 1
    await db.refresh(hotel)
    assert (hotel.status, hotel.pause_reason) == ("paused", billing.UNPAID_PAUSE)
    [s] = await statements(db, hotel)
    assert s.status == "overdue"

    # A claim alone does not count until the admin sees the money.
    claim = await billing.claim(db, hotel.id, code="tk11aa22bb", amount=85, user_id=owner.id)
    assert claim.mpesa_code == "TK11AA22BB" and claim.status == "pending"
    await billing.weekly_job(db, friday)
    await db.refresh(hotel)
    assert hotel.status == "paused"

    await billing.confirm(db, claim.id, admin.id, friday)
    await db.refresh(hotel)
    await db.refresh(s)
    assert hotel.status == "active" and hotel.pause_reason is None
    assert s.status == "paid"
    assert await billing.hotel_balance(db, hotel.id) == 0


async def test_admin_pause_is_never_lifted_by_billing(db):
    hotel, _ = await hotel_with_sale(db)
    hotel.status, hotel.pause_reason = "paused", "Kitchen renovation"
    await db.flush()
    await billing.weekly_job(db, next_monday_10am(utcnow()) + timedelta(days=10))
    await db.refresh(hotel)
    assert hotel.pause_reason == "Kitchen renovation"


async def test_over_the_limit_pauses_before_the_due_date(db):
    admin = await make_user(db, "super_admin")
    await settings.update(db, {"hotel_unpaid_limit": 50}, admin.id)
    hotel, _ = await hotel_with_sale(db)
    await billing.weekly_job(db, next_monday_10am(utcnow()))
    await db.refresh(hotel)
    assert hotel.status == "paused"  # owes 85 > 50, even though not overdue


async def test_partial_payment_keeps_statement_open(db):
    hotel, _ = await hotel_with_sale(db)
    admin = await make_user(db, "super_admin")
    monday = next_monday_10am(utcnow())
    await billing.weekly_job(db, monday)
    c = await billing.claim(db, hotel.id, code="TK22BB33CC", amount=50, user_id=admin.id)
    await billing.confirm(db, c.id, admin.id, monday)
    [s] = await statements(db, hotel)
    assert await billing.left_to_pay(db, s) == 35
    await billing.weekly_job(db, monday + timedelta(days=4))
    await db.refresh(s)
    assert s.status == "overdue"


async def test_paying_ahead_carries_forward(db):
    """Money sent before the statement is issued still counts: next statement is smaller."""
    hotel, _ = await hotel_with_sale(db)
    admin = await make_user(db, "super_admin")
    c = await billing.claim(db, hotel.id, code="TK33CC44DD", amount=100, user_id=admin.id)
    await billing.confirm(db, c.id, admin.id, utcnow())
    await billing.weekly_job(db, next_monday_10am(utcnow()))
    [s] = await statements(db, hotel)
    assert s.amount_due == 0 and s.status == "paid"
    assert await billing.hotel_balance(db, hotel.id) == -15  # in credit


async def test_refund_shows_as_credit(db):
    hotel, order = await hotel_with_sale(db)
    await ledger.refund_rest(db, order, reason="Out of stock", approved_by=None)
    await billing.weekly_job(db, next_monday_10am(utcnow()))
    [s] = await statements(db, hotel)
    assert (s.commission_total, s.service_fee_total, s.credits_total) == (65, 20, 85)
    assert s.amount_due == 0 and s.status == "paid"


async def test_confirm_can_correct_amount(db):
    hotel, _ = await hotel_with_sale(db)
    admin = await make_user(db, "super_admin")
    c = await billing.claim(db, hotel.id, code="TK44DD55EE", amount=850, user_id=admin.id)
    await billing.confirm(db, c.id, admin.id, utcnow(), amount=85)
    assert c.amount == 85
    assert await billing.hotel_balance(db, hotel.id) == 0
    again = await billing.confirm(db, c.id, admin.id, utcnow())  # double tap
    assert again.id == c.id and await billing.hotel_balance(db, hotel.id) == 0


async def test_claim_rules(db):
    hotel, _ = await hotel_with_sale(db)
    other = await make_hotel(db)
    owner = await make_user(db, "hotel_admin", hotel)
    admin = await make_user(db, "super_admin")

    c = await billing.claim(db, hotel.id, code="TK55EE66FF", amount=85, user_id=owner.id)
    assert (
        await billing.claim(db, hotel.id, code="TK55EE66FF", amount=85, user_id=owner.id)
    ).id == c.id
    with pytest.raises(AppError) as e:
        await billing.claim(db, other.id, code="TK55EE66FF", amount=85, user_id=owner.id)
    assert e.value.code == "code_used"

    with pytest.raises(AppError) as e:
        await billing.reject(db, c.id, "  ", admin.id)
    assert e.value.code == "reason_required"
    await billing.reject(db, c.id, "Not on our M-Pesa", admin.id)
    with pytest.raises(AppError):
        await billing.confirm(db, c.id, admin.id, utcnow())

    # The hotel corrects the amount and sends it again: back to pending.
    again = await billing.claim(db, hotel.id, code="TK55EE66FF", amount=80, user_id=owner.id)
    assert (again.id, again.status, again.amount, again.note) == (c.id, "pending", 80, None)
    assert await billing.pending_count(db) >= 1


async def test_rider_payout(db):
    hotel = await make_hotel(db)
    rider = await make_user(db, "rider")
    admin = await make_user(db, "super_admin")
    order = await make_order(db, hotel)
    await ledger.record_payment(db, order, amount=order.till_amount, reference="TJ9")
    await ledger.record_rider_fee(db, order, rider_id=rider.id, payout_mode="weekly")
    assert await billing.rider_balance(db, rider.id) == 100
    assert await billing.hotel_balance(db, hotel.id) == 185  # fee held for the rider

    with pytest.raises(AppError) as e:
        await billing.pay_rider(
            db, rider.id, amount=150, code="RP11AA22BB", admin_id=admin.id, now=utcnow()
        )
    assert e.value.code == "bad_amount"
    p = await billing.pay_rider(
        db, rider.id, amount=60, code="rp11aa22bb", admin_id=admin.id, now=utcnow()
    )
    again = await billing.pay_rider(
        db, rider.id, amount=60, code="RP11AA22BB", admin_id=admin.id, now=utcnow()
    )
    assert again.id == p.id
    # A second payout in the same week is fine.
    await billing.pay_rider(
        db, rider.id, amount=40, code="RP22BB33CC", admin_id=admin.id, now=utcnow()
    )
    view = await billing.rider_view(db, rider.id)
    assert view["owed"] == 0 and len(view["payouts"]) == 2
    [row] = [r for r in await billing.riders_overview(db) if r["rider_id"] == str(rider.id)]
    assert row["owed"] == 0 and row["last_payout"]["amount"] in (40, 60)


# --- HTTP -------------------------------------------------------------------------------------


async def test_billing_api(client, db):
    hotel, _ = await hotel_with_sale(db)
    owner = await make_user(db, "hotel_admin", hotel)
    cashier = await make_user(db, "cashier", hotel)
    admin = await make_user(db, "super_admin")
    rider = await make_user(db, "rider")
    await billing.weekly_job(db, next_monday_10am(utcnow() - timedelta(days=7)))  # nothing yet
    await db.flush()

    h = auth_header(owner)
    body = (await client.get("/api/v1/hotel/billing", headers=h)).json()
    assert body["pay_to"] == "254742554713" and body["balance"] == 85
    assert (
        await client.get("/api/v1/hotel/billing", headers=auth_header(cashier))
    ).status_code == 403

    r = await client.post(
        "/api/v1/hotel/billing/payments", json={"mpesa_code": "TK66FF77GG", "amount": 85}, headers=h
    )
    assert r.status_code == 201 and r.json()["status"] == "pending"
    bad = await client.post(
        "/api/v1/hotel/billing/payments", json={"mpesa_code": "x", "amount": 85}, headers=h
    )
    assert bad.status_code == 422

    a = auth_header(admin)
    assert (await client.get("/api/v1/admin/billing/pending/count", headers=a)).json()[
        "pending"
    ] >= 1
    over = (await client.get("/api/v1/admin/billing", headers=a)).json()
    [p] = [p for p in over["pending"] if p["mpesa_code"] == "TK66FF77GG"]
    assert p["hotel_name"] == hotel.name
    assert (await client.get("/api/v1/admin/billing", headers=h)).status_code == 403

    ok = await client.post(f"/api/v1/admin/billing/payments/{p['id']}/confirm", json={}, headers=a)
    assert ok.json()["status"] == "confirmed"
    body = (await client.get("/api/v1/hotel/billing", headers=h)).json()
    assert body["balance"] == 0 and body["payments"][0]["status"] == "confirmed"

    detail = (await client.get(f"/api/v1/admin/billing/hotels/{hotel.id}", headers=a)).json()
    assert detail["hotel_name"] == hotel.name

    earnings = (await client.get("/api/v1/rider/earnings", headers=auth_header(rider))).json()
    assert earnings == {"owed": 0, "payouts": []}


async def test_statements_are_unique_per_week(db):
    hotel, _ = await hotel_with_sale(db)
    monday = next_monday_10am(utcnow())
    week = billing.week_start(billing.kenya_date(monday)) - timedelta(days=7)
    a = await billing.make_statement(db, hotel, week, 3)
    b = await billing.make_statement(db, hotel, week, 3)
    assert a.id == b.id
    n = await db.scalar(
        select(func.count()).select_from(Statement).where(Statement.hotel_id == hotel.id)
    )
    assert n == 1
