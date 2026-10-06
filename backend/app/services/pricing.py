"""Server-side price calculation. Pure: no database, no clock.

Always in this order:
  1. line gross   = (item price + option prices) x quantity
  2. item discount per line (best single item discount; percent floored once)
  3. items_total  = sum of discounted lines
  4. order discount or promo on items_total (best single one; percent floored once)
  5. service fee (+ the eat-in markup on eat-in orders: platform money like the fee)
  6. rider fee (delivery only; in the Till amount only for option A)
  7. platform bonus (stamp card or free delivery; the larger one, never both)
  8. till_amount  = food_net + service_fee + rider_fee_in_till - platform_bonus
Commission is on food_net only, excluding service and rider fees: a flat tier fee or
floor(rate x food_net) for a hotel on a percent deal.
Discounts never take a line or the subtotal below zero. All amounts are whole-KES ints.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.services.settings import HotelRates

MAX_QUANTITY = 20
MAX_LINES = 50
BP = 10_000
EAT = timedelta(hours=3)  # Kenya, no daylight saving


class PricingError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class OptionInfo:
    id: uuid.UUID
    group_name: str
    name: str
    price_delta: int
    is_archived: bool = False


@dataclass(frozen=True)
class ProductInfo:
    id: uuid.UUID
    name: str
    price: int
    options: dict[uuid.UUID, OptionInfo] = field(default_factory=dict)
    is_sold_out: bool = False
    is_archived: bool = False


@dataclass(frozen=True)
class DiscountInfo:
    id: uuid.UUID
    scope: str  # item | order
    kind: str  # percent (value in bp) | fixed (value in KES; per unit for item scope)
    value: int
    starts_at: datetime
    ends_at: datetime | None = None
    product_id: uuid.UUID | None = None
    min_spend: int = 0
    promo_code: str | None = None
    max_uses: int | None = None
    uses_so_far: int = 0
    is_active: bool = True
    days_mask: int | None = None  # happy hour: Mon = 1 ... Sun = 64
    daily_from: int | None = None  # minutes from midnight, Kenya time
    daily_to: int | None = None


@dataclass(frozen=True)
class Bonuses:
    """Platform bonuses this customer may get on this order (worked out by services/bonus.py)."""

    stamp_reward: int = 0  # KES off: a stamp-card reward is due (0 = none)
    free_delivery_min_food: int = 0  # free delivery when food_net reaches this (0 = off)


@dataclass(frozen=True)
class CartLine:
    product_id: uuid.UUID
    quantity: int
    option_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class QuoteLine:
    product_id: uuid.UUID
    name: str
    unit_price: int
    options: tuple[OptionInfo, ...]
    options_price: int
    quantity: int
    line_discount: int
    line_total: int
    discount_id: uuid.UUID | None


@dataclass(frozen=True)
class Quote:
    lines: tuple[QuoteLine, ...]
    items_total: int
    order_discount: int
    order_discount_id: uuid.UUID | None
    food_net: int
    service_fee: int  # includes eat_in_fee
    rider_fee: int
    rider_fee_in_till: int
    till_amount: int
    commission_bp: int
    commission_amount: int
    platform_bonus: int
    bonus_kind: str | None  # "stamp" | "free_delivery"
    promo_discount_id: uuid.UUID | None  # the promo, if it was applied
    promo_error: str | None  # why a supplied promo code was not applied
    eat_in_fee: int = 0


def pct(bp: int, amount: int) -> int:
    """Percentage of a whole-KES amount, rounded down once."""
    return bp * amount // BP


def _is_live(d: DiscountInfo, now: datetime) -> bool:
    if not (d.is_active and d.starts_at <= now and (d.ends_at is None or now < d.ends_at)):
        return False
    local = now + EAT  # happy-hour windows are Kenya time
    if d.days_mask is not None and not d.days_mask & (1 << local.weekday()):
        return False
    if d.daily_from is not None and d.daily_to is not None:
        minute = local.hour * 60 + local.minute
        return d.daily_from <= minute < d.daily_to
    return True


def _discount_amount(d: DiscountInfo, base: int, quantity: int = 1) -> int:
    raw = pct(d.value, base) if d.kind == "percent" else d.value * quantity
    return min(raw, base)


def check_promo(
    promo: DiscountInfo | None, code: str, now: datetime, gross: int, phone_used: bool
) -> str | None:
    """Return None if the promo can be used, else an error code."""
    if promo is None or promo.promo_code != code:
        return "promo_unknown"
    if not promo.is_active:
        return "promo_disabled"
    if now < promo.starts_at:
        return "promo_not_started"
    if promo.ends_at is not None and now >= promo.ends_at:
        return "promo_ended"
    if gross < promo.min_spend:
        return "promo_min_spend"
    if phone_used:
        return "promo_already_used"
    if promo.max_uses is not None and promo.uses_so_far >= promo.max_uses:
        return "promo_limit_reached"
    return None


def calculate(
    *,
    cart: list[CartLine],
    products: dict[uuid.UUID, ProductInfo],
    discounts: list[DiscountInfo],
    order_type: str,
    rider_fee_mode: str,
    rates: HotelRates,
    now: datetime,
    promo_code: str | None = None,
    promo: DiscountInfo | None = None,
    phone_used_promo: bool = False,
    bonuses: Bonuses | None = None,
) -> Quote:
    """`discounts` are the hotel's automatic (non-promo) discounts; `promo` is the discount
    looked up by `promo_code`, if any. Unknown or unavailable items raise PricingError."""
    _check_type(order_type, rider_fee_mode)
    if not cart:
        raise PricingError("cart_empty", "Add at least one item")
    if len(cart) > MAX_LINES:
        raise PricingError("cart_too_large", f"At most {MAX_LINES} lines per order")

    # Step 1: gross line amounts.
    priced: list[tuple[ProductInfo, tuple[OptionInfo, ...], int, CartLine]] = []
    for line in cart:
        if not 1 <= line.quantity <= MAX_QUANTITY:
            raise PricingError("bad_quantity", f"Quantity must be 1 to {MAX_QUANTITY}")
        product = products.get(line.product_id)
        if product is None or product.is_archived:
            raise PricingError("item_unavailable", "An item in your cart is no longer on the menu")
        if product.is_sold_out:
            raise PricingError("item_sold_out", f"{product.name} is sold out")
        if len(set(line.option_ids)) != len(line.option_ids):
            raise PricingError("bad_option", "An option was chosen twice")
        options = []
        for oid in line.option_ids:
            opt = product.options.get(oid)
            if opt is None or opt.is_archived:
                raise PricingError("bad_option", f"An option for {product.name} is unavailable")
            options.append(opt)
        options_price = sum(o.price_delta for o in options)
        gross = (product.price + options_price) * line.quantity
        priced.append((product, tuple(options), gross, line))

    gross_total = sum(g for _, _, g, _ in priced)

    promo_error = None
    usable_promo = None
    if promo_code and promo_code.strip():
        code = promo_code.strip().upper()
        promo_error = check_promo(promo, code, now, gross_total, phone_used_promo)
        if promo_error is None:
            usable_promo = promo

    live = [d for d in discounts if d.promo_code is None and _is_live(d, now)]
    if usable_promo is not None:
        live.append(usable_promo)
    live = [d for d in live if gross_total >= d.min_spend]

    # Step 2-3: best single item discount per line.
    lines = []
    for product, options, gross, line in priced:
        best_amount, best_id = 0, None
        for d in live:
            if d.scope == "item" and d.product_id == product.id:
                amount = _discount_amount(d, gross, line.quantity)
                if amount > best_amount:
                    best_amount, best_id = amount, d.id
        lines.append(
            QuoteLine(
                product_id=product.id,
                name=product.name,
                unit_price=product.price,
                options=options,
                options_price=sum(o.price_delta for o in options),
                quantity=line.quantity,
                line_discount=best_amount,
                line_total=gross - best_amount,
                discount_id=best_id,
            )
        )
    items_total = sum(ln.line_total for ln in lines)

    # Step 4: best single order discount (automatic or promo).
    order_discount, order_discount_id = 0, None
    for d in live:
        if d.scope == "order":
            amount = _discount_amount(d, items_total)
            if amount > order_discount:
                order_discount, order_discount_id = amount, d.id
    food_net = items_total - order_discount

    promo_applied = usable_promo is not None and (
        order_discount_id == usable_promo.id
        or any(ln.discount_id == usable_promo.id for ln in lines)
    )
    if usable_promo is not None and not promo_applied:
        promo_error = "promo_not_better"

    # Steps 5-6.
    eat_in_fee = rates.eat_in_fee if order_type == "eat_in" else 0
    service_fee = rates.service_fee + eat_in_fee
    rider_fee = rates.rider_fee if order_type == "delivery" else 0
    rider_fee_in_till = rider_fee if rider_fee_mode == "included" else 0

    # Step 7: one platform bonus. Free delivery only when the rider fee goes through the Till
    # (option A), so the rider is still paid by the hotel as usual.
    bonus, bonus_kind = 0, None
    if bonuses is not None:
        stamp = min(bonuses.stamp_reward, food_net)
        min_food = bonuses.free_delivery_min_food
        free = rider_fee_in_till if min_food and food_net >= min_food else 0
        if stamp or free:
            bonus, bonus_kind = (stamp, "stamp") if stamp >= free else (free, "free_delivery")
    till_amount = food_net + service_fee + rider_fee_in_till - bonus

    return Quote(
        lines=tuple(lines),
        items_total=items_total,
        order_discount=order_discount,
        order_discount_id=order_discount_id,
        food_net=food_net,
        service_fee=service_fee,
        rider_fee=rider_fee,
        rider_fee_in_till=rider_fee_in_till,
        till_amount=till_amount,
        commission_bp=rates.commission_bp,
        commission_amount=rates.commission_for(food_net),
        platform_bonus=bonus,
        bonus_kind=bonus_kind,
        promo_discount_id=usable_promo.id if promo_applied else None,
        promo_error=promo_error,
        eat_in_fee=eat_in_fee,
    )


def _check_type(order_type: str, rider_fee_mode: str) -> None:
    if order_type in ("pickup", "eat_in") and rider_fee_mode == "none":
        return
    if order_type == "delivery" and rider_fee_mode in ("included", "cash"):
        return
    raise PricingError("bad_order_type", "Choose delivery (fee option A or B), pickup or eat in")
