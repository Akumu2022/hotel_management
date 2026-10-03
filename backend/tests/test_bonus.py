"""D19: commission tiers, platform bonuses (stamp card, free delivery, daily budget), happy hour."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Customer, LedgerEntry, Order, Refund
from app.services import bonus, ledger, payments, settings
from app.services.pricing import Bonuses, CartLine, DiscountInfo, ProductInfo, calculate
from app.services.settings import DEFAULTS, HotelRates
from tests.factories import make_hotel, make_order, make_user
from tests.test_ordering import body, fixed_clock, key, shop  # noqa: F401  (fixtures)

TIERS = HotelRates(
    commission_bp=0,
    service_fee=20,
    rider_fee=100,
    commission_tiers=DEFAULTS.tiers,
    commission_step=1000,
    commission_step_fee=10,
)
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)  # Friday 12:00 in Nairobi


def product(price: int) -> ProductInfo:
    return ProductInfo(uuid.uuid4(), "Food", price)


def price(food: int, order_type="delivery", mode="included", rates=TIERS, **kw):
    p = product(food)
    return calculate(
        cart=[CartLine(p.id, 1)],
        products={p.id: p},
        discounts=kw.pop("discounts", []),
        order_type=order_type,
        rider_fee_mode=mode,
        rates=rates,
        now=kw.pop("now", NOW),
        **kw,
    )


# --- Commission tiers ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("food", "fee"),
    [
        (10, 10),  # never more than the food itself
        (499, 20),
        (500, 20),
        (501, 30),
        (1000, 30),
        (1001, 40),
        (2000, 40),
        (3500, 60),
        (5000, 70),
        (5001, 80),  # +10 for every started 1,000 above the last tier
        (6000, 80),
        (6001, 90),
        (12000, 140),
    ],
)
def test_tier_fee(food, fee):
    assert TIERS.commission_for(food) == fee


def test_tiers_are_on_food_only_not_rider_or_service_fee():
    a = price(480, mode="included")  # Till 600 with the rider fee, food still under 500
    b = price(480, mode="cash")
    assert (a.till_amount, a.commission_amount) == (600, 20)
    assert (b.till_amount, b.commission_amount) == (500, 20)
    assert a.commission_bp == 0


def test_tiers_must_go_up():
    with pytest.raises(ValueError):
        settings.PlatformSettings(
            commission_tiers=[{"up_to": 1000, "fee": 30}, {"up_to": 500, "fee": 20}]
        )


# --- Bonuses in pricing -------------------------------------------------------------------------


def test_stamp_reward_lowers_till_but_not_food_or_commission():
    q = price(650, bonuses=Bonuses(stamp_reward=100))
    assert (q.food_net, q.commission_amount) == (650, 30)
    assert (q.platform_bonus, q.bonus_kind, q.till_amount) == (100, "stamp", 670)


def test_stamp_never_more_than_food():
    q = price(60, order_type="pickup", mode="none", bonuses=Bonuses(stamp_reward=100))
    assert (q.platform_bonus, q.till_amount) == (60, 20)


def test_free_delivery_only_for_option_a_above_minimum():
    on = Bonuses(free_delivery_min_food=1500)
    assert price(1500, bonuses=on).platform_bonus == 100
    assert price(1500, bonuses=on).till_amount == 1520
    assert price(1499, bonuses=on).platform_bonus == 0
    assert price(1500, mode="cash", bonuses=on).platform_bonus == 0  # fee paid at the door
    assert price(1500, "pickup", "none", bonuses=on).platform_bonus == 0


def test_one_bonus_per_order_the_larger():
    both = Bonuses(stamp_reward=150, free_delivery_min_food=1000)
    assert price(1200, bonuses=both).bonus_kind == "stamp"
    both = Bonuses(stamp_reward=50, free_delivery_min_food=1000)
    q = price(1200, bonuses=both)
    assert (q.bonus_kind, q.platform_bonus) == ("free_delivery", 100)


# --- Happy hour ----------------------------------------------------------------------------------


def happy(**kw) -> DiscountInfo:
    return DiscountInfo(
        id=uuid.uuid4(),
        scope="order",
        kind="percent",
        value=2000,
        starts_at=NOW - timedelta(days=30),
        **kw,
    )


@pytest.mark.parametrize(
    ("utc_hour", "days_mask", "applies"),
    [
        (12, None, True),  # 15:00 Nairobi, inside 15:00-17:00
        (13, None, True),
        (14, None, False),  # 17:00: window ended
        (11, None, False),  # 14:00: not started
        (12, 16, True),  # Friday = 1 << 4
        (12, 1 | 2, False),  # Mon-Tue only
    ],
)
def test_happy_hour_window_is_kenya_time(utc_hour, days_mask, applies):
    d = happy(days_mask=days_mask, daily_from=15 * 60, daily_to=17 * 60)
    q = price(1000, discounts=[d], now=NOW.replace(hour=utc_hour))
    assert (q.order_discount == 200) is applies


# --- Ledger --------------------------------------------------------------------------------------


async def bonus_order(db, hotel, *, bonus_amount=100, kind="stamp"):
    order = await make_order(db, hotel, rates=TIERS)
    order.platform_bonus, order.bonus_kind = bonus_amount, kind
    order.till_amount -= bonus_amount
    await db.flush()
    return order


async def entries(db, order_id):
    rows = (await db.execute(select(LedgerEntry).where(LedgerEntry.order_id == order_id))).scalars()
    out: dict[str, int] = {}
    for r in rows:
        out[r.entry_type] = out.get(r.entry_type, 0) + r.amount
    return out


async def test_platform_owes_hotel_the_bonus(db):
    hotel = await make_hotel(db)
    order = await bonus_order(db, hotel)
    cashier = await make_user(db, "cashier", hotel)
    await payments.confirm_manual(
        db,
        order.id,
        code="SJK3BONUS1",
        amount=670,
        paid_at=None,
        cashier_id=cashier.id,
        now=datetime.now(UTC),
    )
    e = await entries(db, order.id)
    assert e == {"till_received": 670, "commission": 30, "service_fee": 20, "bonus_credit": 100}
    # The hotel still nets its full sale: 670 in the Till + 100 credit - 30 - 20.
    assert e["till_received"] + e["bonus_credit"] - e["commission"] - e["service_fee"] == 720


async def test_full_refund_of_bonus_order_reverses_everything(db):
    hotel = await make_hotel(db)
    order = await bonus_order(db, hotel)
    await ledger.record_payment(db, order, amount=670)
    refund = await ledger.refund_rest(db, order, reason="Rejected", approved_by=None)
    assert refund.amount == 670  # what the customer actually paid
    e = await entries(db, order.id)
    assert e["commission_reversal"] == 30
    assert e["service_fee_reversal"] == 20
    assert e["bonus_credit_reversal"] == 100


async def test_partial_refund_reverses_tier_fee_pro_rata(db):
    hotel = await make_hotel(db)
    order = await make_order(db, hotel, rates=TIERS)  # food 650, fee 30
    await ledger.record_payment(db, order, amount=770)
    await ledger.approve_refund(db, order.id, food=325, reason="Half", approved_by=None)
    assert (await entries(db, order.id))["commission_reversal"] == 15


# --- Stamp card and budget ------------------------------------------------------------------


async def customer(db, completed: int) -> Customer:
    c = Customer(
        phone="2547" + uuid.uuid4().hex[:8].translate(str.maketrans("abcdef", "123456")),
        name="Wafula",
        completed_orders=completed,
    )
    db.add(c)
    await db.flush()
    return c


async def test_stamp_card_progress_and_reward(db):
    s = DEFAULTS
    assert (await bonus.stamp_card(db, s, await customer(db, 3))).have == 3
    ready = await bonus.stamp_card(db, s, await customer(db, 5))
    assert (ready.reward_ready, ready.have) == (True, 5)
    assert (await bonus.stamp_card(db, s, None)).reward_ready is False


async def test_used_stamp_counts_until_order_is_cancelled(db):
    hotel = await make_hotel(db)
    order = await bonus_order(db, hotel)
    c = await db.get(Customer, order.customer_phone)
    c.completed_orders = 5
    await db.flush()
    assert (await bonus.stamp_card(db, DEFAULTS, c)).reward_ready is False  # already used
    order.status = "cancelled"
    await db.flush()
    assert (await bonus.stamp_card(db, DEFAULTS, c)).reward_ready is True  # given back


async def test_daily_budget_stops_bonuses(db):
    hotel = await make_hotel(db)
    s = DEFAULTS.model_copy(update={"bonus_daily_budget": 150})
    c = await customer(db, 5)
    offered, _ = await bonus.offer(db, s, c, rider_fee=100, now=datetime.now(UTC), placing=True)
    assert offered.stamp_reward == 100
    await bonus_order(db, hotel)  # spends 100 of today's 150
    offered, _ = await bonus.offer(db, s, c, rider_fee=100, now=datetime.now(UTC), placing=False)
    assert (offered.stamp_reward, offered.free_delivery_min_food) == (0, 0)


# --- End to end through the API ------------------------------------------------------------


async def test_fifth_order_gets_stamp_reward_once(client, db, shop, fixed_clock):  # noqa: F811
    hotel, product = shop
    db.add(Customer(phone="254712000111", name="Achieng", completed_orders=5))
    await db.flush()
    quote = (
        await client.post(
            "/api/v1/quotes",
            json={
                "hotel_slug": hotel.slug,
                "lines": [{"product_id": str(product.id), "quantity": 1}],
                "type": "pickup",
                "rider_fee_mode": "none",
                "phone": "0712000111",
            },
        )
    ).json()
    assert (quote["bonus_kind"], quote["platform_bonus"], quote["till_amount"]) == (
        "stamp",
        100,
        570,
    )
    assert (quote["stamp_every"], quote["stamps_have"]) == (5, 5)

    pickup = {
        "type": "pickup",
        "rider_fee_mode": "none",
        "landmark": None,
        "lat": None,
        "lng": None,
    }
    r = await client.post(
        "/api/v1/orders", headers=key(), json=body(hotel, product, **pickup, expected_total=570)
    )
    assert r.status_code == 201, r.text
    order = (await db.execute(select(Order).where(Order.code == r.json()["code"]))).scalar_one()
    assert (order.platform_bonus, order.bonus_kind, order.till_amount) == (100, "stamp", 570)

    r = await client.post(
        "/api/v1/orders", headers=key(), json=body(hotel, product, **pickup, expected_total=570)
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "price_changed"  # used up
    assert (await db.execute(select(Refund))).first() is None


async def test_hotel_creates_happy_hour(client, db):
    from tests.factories import auth_header

    hotel = await make_hotel(db)
    admin = auth_header(await make_user(db, "hotel_admin", hotel))
    r = await client.post(
        "/api/v1/hotel/discounts",
        headers=admin,
        json={
            "scope": "order",
            "kind": "percent",
            "percent": 15,
            "starts_at": "2026-10-01T00:00:00Z",
            "days_mask": 31,
            "daily_from": 900,
            "daily_to": 1020,
        },
    )
    assert r.status_code == 201, r.text
    assert (r.json()["days_mask"], r.json()["daily_from"], r.json()["daily_to"]) == (31, 900, 1020)
    r = await client.post(
        "/api/v1/hotel/discounts",
        headers=admin,
        json={
            "scope": "order",
            "kind": "percent",
            "percent": 15,
            "starts_at": "2026-10-01T00:00:00Z",
            "daily_from": 1020,
            "daily_to": 900,
        },
    )
    assert r.status_code == 422
