"""The admin's way out of a delivery stuck on the road."""

from sqlalchemy import select

from app.models import Customer, LedgerEntry, Order, ReviewItem
from tests.factories import auth_header, make_hotel, make_user
from tests.test_delivery import API, make_rider, ready_delivery
from tests.test_tracking import deliver


async def stuck(client, db, **kw):
    order = await ready_delivery(db, **kw)
    rider = await make_rider(db)
    await deliver(client, db, order, rider)
    admin = auth_header(await make_user(db, "super_admin"))
    return order, rider, admin


def close(client, admin, order, **body):
    return client.post(f"{API}/admin/dispatch/{order.id}/close", headers=admin, json=body)


async def test_failed_close_files_the_usual_review_and_frees_the_rider(client, db):
    order, rider, admin = await stuck(client, db)
    r = await close(client, admin, order, outcome="failed", reason="Rider's phone is off")
    assert r.status_code == 200 and r.json()["status"] == "failed_delivery"

    [item] = (
        (await db.execute(select(ReviewItem).where(ReviewItem.order_id == order.id)))
        .scalars()
        .all()
    )
    assert item.type == "failed_delivery" and "Rider's phone is off" in item.reason
    # The rider has no active job any more.
    me = (await client.get(f"{API}/rider/jobs", headers=auth_header(rider))).json()
    assert [j for j in me if j["mine"]] == []
    # The existing decision still applies: the admin says whose fault it was.
    r = await client.post(
        f"{API}/admin/review-items/{item.id}/resolve",
        headers=admin,
        json={"action": "rider_fault"},
    )
    assert r.status_code == 200, r.text


async def test_delivered_close_counts_for_the_customer_and_pays_the_rider(client, db):
    order, rider, admin = await stuck(client, db)
    before = await db.scalar(
        select(Customer.completed_orders).where(Customer.phone == order.customer_phone)
    )
    r = await close(client, admin, order, outcome="delivered", reason="Customer confirmed by phone")
    assert r.status_code == 200 and r.json()["status"] == "delivered"
    await db.refresh(order)
    assert order.delivered_at is not None and order.closed_at is not None
    after = await db.scalar(
        select(Customer.completed_orders).where(Customer.phone == order.customer_phone)
    )
    assert after == (before or 0) + 1
    # Closing twice changes nothing.
    again = await close(client, admin, order, outcome="failed", reason="Second tap by mistake")
    assert again.status_code == 200 and again.json()["status"] == "delivered"


async def test_cash_fee_delivery_needs_to_know_if_the_rider_was_paid(client, db):
    order, rider, admin = await stuck(client, db, mode="cash")
    r = await close(client, admin, order, outcome="delivered", reason="Customer confirmed by phone")
    assert r.status_code == 422 and r.json()["error"]["code"] == "rider_paid_cash_required"
    r = await close(
        client,
        admin,
        order,
        outcome="delivered",
        reason="Customer confirmed by phone",
        rider_paid_cash=False,
    )
    assert r.status_code == 200
    kinds = (
        (await db.execute(select(LedgerEntry.entry_type).where(LedgerEntry.order_id == order.id)))
        .scalars()
        .all()
    )
    assert "rider_compensation" in kinds  # the platform pays the rider the customer did not


async def test_only_stuck_deliveries_and_only_the_super_admin(client, db):
    order, rider, admin = await stuck(client, db)
    staff = auth_header(await make_user(db, "super_admin"))
    hotel_admin = auth_header(await make_user(db, "hotel_admin", await make_hotel(db)))
    assert (
        await close(client, hotel_admin, order, outcome="failed", reason="Not allowed")
    ).status_code in (401, 403)
    assert (await close(client, staff, order, outcome="failed", reason="ab")).status_code == 422

    waiting = await ready_delivery(db)  # still at the hotel: not stuck on the road
    r = await close(client, admin, waiting, outcome="failed", reason="Too early to close")
    assert r.status_code == 409
    assert (await db.get(Order, waiting.id)).status == "ready"
