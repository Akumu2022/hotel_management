"""Every calculation path (spec section 14), including the section 11 worked example."""

import uuid
from datetime import timedelta

import pytest

from app.services.pricing import (
    CartLine,
    DiscountInfo,
    OptionInfo,
    PricingError,
    ProductInfo,
    calculate,
)
from app.services.settings import HotelRates
from tests.factories import NOW

RATES = HotelRates(commission_bp=1000, service_fee=20, rider_fee=100)

PILAU = ProductInfo(uuid.uuid4(), "Pilau", 650)
EXTRA_MEAT = OptionInfo(uuid.uuid4(), "Extras", "Extra meat", 80)
KACHUMBARI = OptionInfo(uuid.uuid4(), "Extras", "Kachumbari", 30)
OLD_OPTION = OptionInfo(uuid.uuid4(), "Extras", "Old", 10, is_archived=True)
CHAPATI = ProductInfo(
    uuid.uuid4(),
    "Chapati",
    25,
    options={o.id: o for o in (EXTRA_MEAT, KACHUMBARI, OLD_OPTION)},
)
PRODUCTS = {p.id: p for p in (PILAU, CHAPATI)}


def quote(cart, order_type="pickup", mode="none", discounts=(), rates=RATES, **kw):
    return calculate(
        cart=cart,
        products=kw.pop("products", PRODUCTS),
        discounts=list(discounts),
        order_type=order_type,
        rider_fee_mode=mode,
        rates=rates,
        now=kw.pop("now", NOW),
        **kw,
    )


def discount(scope="order", kind="percent", value=1000, **kw) -> DiscountInfo:
    return DiscountInfo(
        id=uuid.uuid4(),
        scope=scope,
        kind=kind,
        value=value,
        starts_at=kw.pop("starts_at", NOW - timedelta(days=1)),
        **kw,
    )


# --- Section 11 worked example ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("order_type", "mode", "till", "rider_cash"),
    [
        ("delivery", "included", 770, 0),  # option A
        ("delivery", "cash", 670, 100),  # option B
        ("pickup", "none", 670, 0),
    ],
)
def test_worked_example(order_type, mode, till, rider_cash):
    q = quote([CartLine(PILAU.id, 1)], order_type, mode)
    assert q.food_net == 650
    assert q.till_amount == till
    assert q.rider_fee - q.rider_fee_in_till == rider_cash
    hotel_owes = q.commission_amount + q.service_fee
    assert hotel_owes == 85
    # Hotel keeps the same under every option: Till money - owed - rider fee passed on.
    assert q.till_amount - hotel_owes - q.rider_fee_in_till == 585


def test_bad_order_type_combinations():
    for order_type, mode in [("pickup", "included"), ("delivery", "none"), ("x", "none")]:
        with pytest.raises(PricingError) as e:
            quote([CartLine(PILAU.id, 1)], order_type, mode)
        assert e.value.code == "bad_order_type"


# --- Lines, options, quantities -----------------------------------------------------------------


def test_options_and_quantity():
    q = quote([CartLine(CHAPATI.id, 3, (EXTRA_MEAT.id, KACHUMBARI.id))])
    (line,) = q.lines
    assert line.options_price == 110
    assert line.line_total == (25 + 110) * 3 == 405
    assert q.items_total == 405


@pytest.mark.parametrize("qty", [0, -1, 21])
def test_quantity_limits(qty):
    with pytest.raises(PricingError) as e:
        quote([CartLine(PILAU.id, qty)])
    assert e.value.code == "bad_quantity"


def test_quantity_bounds_accepted():
    assert quote([CartLine(PILAU.id, 20)]).items_total == 13000
    assert quote([CartLine(PILAU.id, 1)]).items_total == 650


def test_empty_cart():
    with pytest.raises(PricingError, match="at least one"):
        quote([])


@pytest.mark.parametrize(
    ("products", "line", "code"),
    [
        ({}, CartLine(PILAU.id, 1), "item_unavailable"),
        (
            {PILAU.id: ProductInfo(PILAU.id, "Pilau", 650, is_archived=True)},
            CartLine(PILAU.id, 1),
            "item_unavailable",
        ),
        (
            {PILAU.id: ProductInfo(PILAU.id, "Pilau", 650, is_sold_out=True)},
            CartLine(PILAU.id, 1),
            "item_sold_out",
        ),
        (PRODUCTS, CartLine(CHAPATI.id, 1, (uuid.uuid4(),)), "bad_option"),
        (PRODUCTS, CartLine(CHAPATI.id, 1, (OLD_OPTION.id,)), "bad_option"),
        (PRODUCTS, CartLine(CHAPATI.id, 1, (EXTRA_MEAT.id, EXTRA_MEAT.id)), "bad_option"),
        (PRODUCTS, CartLine(PILAU.id, 1, (EXTRA_MEAT.id,)), "bad_option"),  # other product's
    ],
)
def test_unavailable_items_and_options(products, line, code):
    with pytest.raises(PricingError) as e:
        quote([line], products=products)
    assert e.value.code == code


def test_client_prices_are_not_an_input():
    # CartLine has no price field at all: the server's catalogue is the only price source.
    assert "price" not in CartLine.__dataclass_fields__


# --- Discounts and rounding ---------------------------------------------------------------------


def test_item_percent_discount_rounds_down_once():
    # 15 % of 3 x 25 = 11.25 -> 11 (one floor on the line, not per unit).
    d = discount("item", "percent", 1500, product_id=CHAPATI.id)
    q = quote([CartLine(CHAPATI.id, 3)], discounts=[d])
    assert q.lines[0].line_discount == 11
    assert q.lines[0].line_total == 64


def test_item_fixed_discount_is_per_unit_and_capped():
    d = discount("item", "fixed", 10, product_id=CHAPATI.id)
    assert quote([CartLine(CHAPATI.id, 4)], discounts=[d]).lines[0].line_discount == 40
    big = discount("item", "fixed", 500, product_id=CHAPATI.id)
    q = quote([CartLine(CHAPATI.id, 2)], discounts=[big])
    assert q.lines[0].line_total == 0  # never below zero


def test_best_single_item_discount_wins():
    a = discount("item", "percent", 1000, product_id=PILAU.id)  # 65
    b = discount("item", "fixed", 100, product_id=PILAU.id)  # 100
    q = quote([CartLine(PILAU.id, 1)], discounts=[a, b])
    assert q.lines[0].line_discount == 100
    assert q.lines[0].discount_id == b.id


def test_order_discount_applies_after_item_discounts():
    item = discount("item", "fixed", 50, product_id=PILAU.id)
    order = discount("order", "percent", 1000)
    q = quote([CartLine(PILAU.id, 1)], discounts=[item, order])
    assert q.items_total == 600
    assert q.order_discount == 60
    assert q.food_net == 540
    assert q.commission_amount == 54  # on food after all discounts


def test_order_discount_min_spend():
    d = discount("order", "fixed", 100, min_spend=1000)
    assert quote([CartLine(PILAU.id, 1)], discounts=[d]).order_discount == 0
    assert quote([CartLine(PILAU.id, 2)], discounts=[d]).order_discount == 100


def test_order_discount_never_below_zero():
    d = discount("order", "fixed", 5000)
    q = quote([CartLine(PILAU.id, 1)], discounts=[d])
    assert q.food_net == 0
    assert q.commission_amount == 0
    assert q.till_amount == 20  # service fee is still due


def test_full_percent_discount_gives_zero_food():
    d = discount("order", "percent", 10000)
    q = quote([CartLine(PILAU.id, 1)], "delivery", "included", discounts=[d])
    assert (q.food_net, q.commission_amount, q.till_amount) == (0, 0, 120)


def test_inactive_expired_and_future_discounts_ignored():
    ds = [
        discount("order", "fixed", 100, is_active=False),
        discount("order", "fixed", 100, ends_at=NOW - timedelta(seconds=1)),
        discount("order", "fixed", 100, starts_at=NOW + timedelta(hours=1)),
    ]
    assert quote([CartLine(PILAU.id, 1)], discounts=ds).order_discount == 0


def test_ends_at_is_exclusive():
    d = discount("order", "fixed", 100, ends_at=NOW)
    assert quote([CartLine(PILAU.id, 1)], discounts=[d]).order_discount == 0


def test_commission_rounds_down():
    rates = HotelRates(commission_bp=1250, service_fee=20, rider_fee=100)
    q = quote([CartLine(CHAPATI.id, 3)], rates=rates)  # 75 x 12.5 % = 9.375
    assert q.commission_amount == 9


def test_commission_excludes_fees():
    q = quote([CartLine(PILAU.id, 1)], "delivery", "included")
    assert q.commission_amount == 65


def test_zero_rates():
    q = quote([CartLine(PILAU.id, 1)], rates=HotelRates(0, 0, 0))
    assert (q.commission_amount, q.service_fee, q.till_amount) == (0, 0, 650)


# --- Promo codes --------------------------------------------------------------------------------


def promo(**kw) -> DiscountInfo:
    return discount(
        kw.pop("scope", "order"),
        kw.pop("kind", "fixed"),
        kw.pop("value", 50),
        promo_code="KARIBU",
        **kw,
    )


def test_promo_applies_and_is_case_insensitive():
    p = promo()
    q = quote([CartLine(PILAU.id, 1)], promo_code=" karibu ", promo=p)
    assert q.order_discount == 50
    assert q.promo_discount_id == p.id
    assert q.promo_error is None


@pytest.mark.parametrize(
    ("kw", "phone_used", "error"),
    [
        ({"is_active": False}, False, "promo_disabled"),
        ({"starts_at": NOW + timedelta(days=1)}, False, "promo_not_started"),
        ({"ends_at": NOW}, False, "promo_ended"),
        ({"min_spend": 1000}, False, "promo_min_spend"),
        ({}, True, "promo_already_used"),
        ({"max_uses": 5, "uses_so_far": 5}, False, "promo_limit_reached"),
    ],
)
def test_promo_checks(kw, phone_used, error):
    q = quote(
        [CartLine(PILAU.id, 1)],
        promo_code="KARIBU",
        promo=promo(**kw),
        phone_used_promo=phone_used,
    )
    assert q.promo_error == error
    assert q.order_discount == 0
    assert q.promo_discount_id is None


def test_unknown_promo():
    q = quote([CartLine(PILAU.id, 1)], promo_code="NOPE", promo=None)
    assert q.promo_error == "promo_unknown"


def test_promo_competes_with_automatic_order_discount():
    auto = discount("order", "fixed", 100)
    q = quote([CartLine(PILAU.id, 1)], discounts=[auto], promo_code="KARIBU", promo=promo())
    assert q.order_discount == 100
    assert q.promo_error == "promo_not_better"
    assert q.promo_discount_id is None


def test_item_scope_promo():
    p = promo(scope="item", kind="percent", value=2000, product_id=PILAU.id)
    q = quote([CartLine(PILAU.id, 1)], promo_code="KARIBU", promo=p)
    assert q.lines[0].line_discount == 130
    assert q.promo_discount_id == p.id


def test_promo_codes_are_not_applied_automatically():
    p = promo()
    q = quote([CartLine(PILAU.id, 1)], discounts=[p])
    assert q.order_discount == 0
