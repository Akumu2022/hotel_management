"""D19: dashboards from the ledger, and payment review owned by each hotel."""

from datetime import timedelta

from app.core.time import utcnow
from app.models import OrderItem, ReviewItem
from app.services import ledger, payments
from app.services.settings import DEFAULTS, HotelRates
from tests.factories import auth_header, make_hotel, make_order, make_product, make_user

TIERS = HotelRates(0, 20, 100, commission_tiers=DEFAULTS.tiers)


async def paid(db, hotel, cashier, code, **kw):
    order = await make_order(db, hotel, rates=TIERS, **kw)
    await payments.confirm_manual(
        db,
        order.id,
        code=code,
        amount=order.till_amount,
        paid_at=None,
        cashier_id=cashier.id,
        now=utcnow(),
    )
    return order


async def test_hotel_dashboard_totals_and_scoping(client, db):
    hotel, other = await make_hotel(db), await make_hotel(db)
    cashier = await make_user(db, "cashier", hotel)
    a = await paid(db, hotel, cashier, "SJK3REP001")  # food 650, Till 770, fee 30
    await paid(
        db, hotel, cashier, "SJK3REP002", food=1200, order_type="pickup", rider_fee_mode="none"
    )
    await paid(db, other, await make_user(db, "cashier", other), "SJK3REP003")
    db.add(
        OrderItem(
            order_id=a.id,
            product_id=(await make_product(db, hotel)).id,
            name_snapshot="Pilau",
            unit_price=650,
            options_snapshot=[],
            options_price=0,
            quantity=1,
            line_discount=0,
            line_total=650,
        )
    )
    refund = await ledger.approve_refund(db, a.id, food=100, reason="Cold chips", approved_by=None)
    await ledger.mark_refund_sent(db, refund.id, mpesa_code="RFD0000009", sent_by=None)

    admin = auth_header(await make_user(db, "hotel_admin", hotel))
    body = (await client.get("/api/v1/hotel/reports", headers=admin)).json()
    t = body["totals"]
    assert (t["orders"], t["mpesa"], t["refunds"], t["net_received"]) == (2, 1990, 100, 1890)
    assert (t["food_sales"], t["average_order"], t["deliveries"], t["pickups"]) == (1850, 925, 1, 1)
    # Tier fees 30 + 40, less 30 x 100/650 = 4 reversed for the partial refund.
    assert t["commission"] == 66 and t["service_fee"] == 40
    assert len(body["series"]) == 1 and body["series"][0]["orders"] == 2
    assert body["top_items"] == [{"name": "Pilau", "quantity": 1, "sales": 650}]
    assert sum(body["by_hour"]) == 2
    assert "per_hotel" not in body

    rows = (await client.get("/api/v1/hotel/reports/payments", headers=admin)).json()
    assert sorted(r["kind"] for r in rows) == ["mpesa", "mpesa", "refund"]
    csv = await client.get("/api/v1/hotel/reports/payments?format=csv", headers=admin)
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.text.splitlines()[0].startswith("at,kind,amount")

    cashier_h = auth_header(cashier)
    assert (await client.get("/api/v1/hotel/reports", headers=cashier_h)).status_code == 403


async def test_admin_dashboard_commission_by_hotel_and_filters(client, db):
    h1, h2 = await make_hotel(db), await make_hotel(db)
    await paid(db, h1, await make_user(db, "cashier", h1), "SJK3REP011")
    await paid(db, h2, await make_user(db, "cashier", h2), "SJK3REP012", food=3500)
    admin = auth_header(await make_user(db, "super_admin"))

    body = (await client.get("/api/v1/admin/reports?group=week", headers=admin)).json()
    assert body["totals"]["commission"] == 30 + 60
    assert body["totals"]["earnings"] == 90 + 40  # commission + service fees, no bonuses
    assert [h["earnings"] for h in body["per_hotel"]] == [80, 50]
    one = (await client.get(f"/api/v1/admin/reports?hotel_id={h1.id}", headers=admin)).json()
    assert one["totals"]["orders"] == 1

    today = (utcnow() + timedelta(hours=3)).date()
    old = today - timedelta(days=40)
    r = await client.get(f"/api/v1/admin/reports?start={old}&end={old}", headers=admin)
    assert r.json()["totals"]["orders"] == 0
    r = await client.get(f"/api/v1/admin/reports?start={today}&end={old}", headers=admin)
    assert r.status_code == 422


async def test_payment_review_belongs_to_the_hotel(client, db):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel)
    fresh = ReviewItem(type="underpaid", hotel_id=hotel.id, order_id=order.id, reason="Short")
    stale = ReviewItem(
        type="no_sms",
        hotel_id=hotel.id,
        order_id=order.id,
        reason="Customer entered a code but no SMS arrived",
        created_at=utcnow() - timedelta(minutes=20),
    )
    orphan = ReviewItem(type="parse_failed", reason="Could not read SMS")
    db.add_all([fresh, stale, orphan])
    await db.flush()
    admin = auth_header(await make_user(db, "super_admin"))

    ids = {i["id"] for i in (await client.get("/api/v1/admin/review-items", headers=admin)).json()}
    assert ids == {str(stale.id), str(orphan.id)}  # fresh hotel items are the hotel's alone
    assert (await client.get("/api/v1/admin/review-items/count", headers=admin)).json() == {
        "open": 2
    }

    staff = auth_header(await make_user(db, "cashier", hotel))
    mine = {i["id"] for i in (await client.get("/api/v1/hotel/review-items", headers=staff)).json()}
    assert mine == {str(fresh.id), str(stale.id)}

    # Within 15 minutes a hotel item is the hotel's alone...
    r = await client.post(
        f"/api/v1/admin/review-items/{fresh.id}/resolve", headers=admin, json={"action": "refund"}
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "hotel_item"
    # ...once escalated, the owner can settle it too, so the queue can always be emptied.
    r = await client.post(
        f"/api/v1/admin/review-items/{stale.id}/resolve", headers=admin, json={"action": "dismiss"}
    )
    assert r.status_code == 200 and r.json()["status"] == "resolved"
    await db.refresh(stale)
    assert stale.resolved_by is not None
    r = await client.post(
        f"/api/v1/admin/review-items/{orphan.id}/resolve", headers=admin, json={"action": "dismiss"}
    )
    assert r.status_code == 200
    assert (await client.get("/api/v1/admin/review-items/count", headers=admin)).json() == {
        "open": 0
    }
