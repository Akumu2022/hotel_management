import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.schemas.catalogue import Input
from app.schemas.common import Phone, Schema


class CartLineIn(Input):
    product_id: uuid.UUID
    quantity: int = Field(ge=1, le=20)
    option_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class QuoteIn(Input):
    """What the phone sends: item IDs, options, quantities and choices. Never prices."""

    hotel_slug: str = Field(max_length=80)
    lines: list[CartLineIn] = Field(min_length=1, max_length=50)
    type: Literal["delivery", "pickup", "eat_in"]
    rider_fee_mode: Literal["included", "cash", "none"]
    promo_code: str | None = Field(None, max_length=20)
    phone: Phone | None = None  # lets the quote check "one promo use per phone"
    lat: float | None = Field(None, ge=-90, le=90)  # delivery pin: sets the rider fee
    lng: float | None = Field(None, ge=-180, le=180)

    @model_validator(mode="after")
    def _mode(self):
        if (self.type != "delivery") != (self.rider_fee_mode == "none"):
            raise ValueError("Pickup and eat in have no rider fee; delivery needs option A or B")
        return self


class OrderIn(QuoteIn):
    name: Annotated[str, Field(min_length=2, max_length=120)]
    phone: Phone
    payment_method: Literal["mpesa", "cash"]
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    landmark: str | None = Field(None, max_length=300)
    arrive_at: datetime | None = None  # eat in: when the customer will come to eat
    # The total the customer saw. If the server's total differs, placement is refused with
    # 409 price_changed and the new quote, so the customer confirms the new amount.
    expected_total: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def _delivery(self):
        if self.type == "delivery":
            if self.lat is None or self.lng is None:
                raise ValueError("Drop a pin for the delivery location")
            if not self.landmark or len(self.landmark.strip()) < 3:
                raise ValueError("Describe the delivery spot (e.g. gate colour, building)")
            if self.payment_method != "mpesa":
                raise ValueError("Delivery orders are paid by M-Pesa")
        if self.type == "eat_in":
            if self.arrive_at is None:
                raise ValueError("Choose when you'll arrive")
            if self.payment_method != "mpesa":
                raise ValueError("Eat-in orders are paid first, by M-Pesa")
        return self


class QuoteLineOut(Schema):
    product_id: uuid.UUID
    name: str
    unit_price: int
    options: list[str]
    options_price: int
    quantity: int
    line_discount: int
    line_total: int


class QuoteOut(Schema):
    lines: list[QuoteLineOut]
    items_total: int
    order_discount: int
    food_net: int
    service_fee: int  # includes eat_in_fee
    eat_in_fee: int = 0
    rider_fee: int
    rider_fee_in_till: int
    rider_fee_cash: int  # option B: paid to the rider at the door
    till_amount: int
    promo_applied: bool
    promo_error: str | None
    option_b_allowed: bool
    cash_allowed: bool
    cash_cap: int | None  # first-time numbers paying cash at pickup
    distance_km: float | None = None
    rider_fee_estimated: bool = False  # true until a pin is dropped: fee shown is "from"
    too_far: bool = False
    max_delivery_km: float | None = None
    # Platform bonuses
    platform_bonus: int = 0
    bonus_kind: str | None = None  # stamp | free_delivery
    free_delivery_min_food: int | None = None  # food total for free delivery (option A)
    stamp_every: int = 0  # 0 = no stamp card
    stamps_have: int = 0
    stamp_reward: int = 0


class OrderPlaced(Schema):
    code: str
    tracking_token: str
    status: str
    till_number: str
    till_amount: int
    payment_method: str
    expires_at: datetime | None


class TrackItem(Schema):
    product_id: uuid.UUID
    option_ids: list[uuid.UUID] = []
    name: str
    options: list[str]
    quantity: int
    line_total: int
    thumb_url: str | None = None


class TrackEvent(Schema):
    status: str
    at: datetime


class TrackLive(Schema):
    """Where the rider is, while the food is on the road (customer's live map)."""

    rider_lat: float
    rider_lng: float
    at: datetime
    live: bool  # false when the last position is over 5 minutes old
    dest_lat: float
    dest_lng: float
    hotel_lat: float | None = None
    hotel_lng: float | None = None


class TrackOut(Schema):
    code: str
    status: str
    type: str
    payment_method: str
    rider_fee_mode: str
    hotel_name: str
    hotel_slug: str
    hotel_phone: str
    till_number: str
    till_name: str | None = None  # M-Pesa shows this name before the customer enters their PIN
    hotel_verified: bool = False
    items: list[TrackItem]
    items_total: int
    order_discount: int
    food_net: int
    service_fee: int  # includes eat_in_fee
    eat_in_fee: int = 0
    arrive_at: datetime | None = None
    rider_fee: int
    till_amount: int
    rider_fee_cash: int
    platform_bonus: int = 0
    bonus_kind: str | None = None
    delivery_code: str | None
    customer_trans_code: str | None = None
    distance_km: float | None = None
    landmark: str | None
    expires_at: datetime | None
    prep_minutes: int | None
    reason: str | None
    can_cancel: bool
    created_at: datetime
    events: list[TrackEvent]
    rider_name: str | None = None
    rider_phone: str | None = None
    rider_photo_url: str | None = None
    can_rate: bool = False  # finished and not rated yet
    rated: bool = False
    fee_question: bool = False  # "Did you pay the rider KES X?" awaiting an answer
    live: TrackLive | None = None
