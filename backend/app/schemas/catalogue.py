import uuid
from datetime import datetime, time
from typing import Annotated, Literal

from pydantic import AfterValidator, ConfigDict, Field, model_validator

from app.schemas.common import Phone, Schema

Money = Annotated[int, Field(ge=0, le=1_000_000, strict=True)]
Name = Annotated[str, Field(min_length=1, max_length=80)]


# No distance cap from town: a hotel can be anywhere in Kenya. The box only stops typos
# (swapped or mistyped coordinates landing in the sea or another country).
KENYA_LAT = (-4.8, 5.1)
KENYA_LNG = (33.9, 41.95)


class Input(Schema):
    model_config = ConfigDict(extra="forbid")


# --- Categories -------------------------------------------------------------------------------


class CategoryOut(Schema):
    id: uuid.UUID
    name: str
    sort_order: int
    available_from: time | None
    available_to: time | None


def _window_pair(obj):
    if (obj.available_from is None) != (obj.available_to is None):
        raise ValueError("Set both 'available from' and 'available to', or neither")
    if obj.available_from is not None and obj.available_from == obj.available_to:
        raise ValueError("'Available from' and 'available to' cannot be the same")
    return obj


class CategoryIn(Input):
    name: Name
    sort_order: int = Field(0, ge=0, le=10_000)
    available_from: time | None = None
    available_to: time | None = None

    _check = model_validator(mode="after")(_window_pair)


class CategoryPatch(Input):
    name: Name | None = None
    sort_order: int | None = Field(None, ge=0, le=10_000)
    available_from: time | None = None
    available_to: time | None = None


# --- Products and options ---------------------------------------------------------------------


class OptionOut(Schema):
    id: uuid.UUID
    group_name: str
    name: str
    price_delta: int
    sort_order: int
    is_archived: bool


class OptionIn(Input):
    group_name: Name
    name: Name
    price_delta: Money = 0
    sort_order: int = Field(0, ge=0, le=10_000)


class OptionPatch(Input):
    group_name: Name | None = None
    name: Name | None = None
    price_delta: Money | None = None
    sort_order: int | None = Field(None, ge=0, le=10_000)
    is_archived: bool | None = None


class ProductOut(Schema):
    id: uuid.UUID
    category_id: uuid.UUID
    name: str
    description: str
    price: int
    prep_minutes: int
    is_sold_out: bool
    sold_out_until: datetime | None = None
    is_archived: bool
    image_url: str | None = None
    thumb_url: str | None = None
    options: list[OptionOut] = []


class ProductIn(Input):
    category_id: uuid.UUID
    name: Annotated[str, Field(min_length=1, max_length=120)]
    description: str = Field("", max_length=1000)
    price: Money
    prep_minutes: int = Field(15, ge=1, le=240)
    image_key: str | None = Field(None, max_length=200)


class ProductPatch(Input):
    category_id: uuid.UUID | None = None
    name: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    description: str | None = Field(None, max_length=1000)
    price: Money | None = None
    prep_minutes: int | None = Field(None, ge=1, le=240)
    is_sold_out: bool | None = None
    back_tomorrow: bool | None = None  # with is_sold_out: back on sale at the next opening
    is_archived: bool | None = None
    image_key: str | None = Field(None, max_length=200)  # explicit null removes the photo


class UploadOut(Schema):
    image_key: str
    thumb_key: str
    image_url: str
    thumb_url: str


# --- Discounts and offers ---------------------------------------------------------------------


def _upper_code(v: str | None) -> str | None:
    if v is None:
        return None
    v = v.strip().upper()
    if not v.isalnum() or not 3 <= len(v) <= 20:
        raise ValueError("Promo codes are 3-20 letters or digits")
    return v


PromoCode = Annotated[str, AfterValidator(_upper_code)]


class DiscountOut(Schema):
    id: uuid.UUID
    scope: str
    product_id: uuid.UUID | None
    kind: str
    value: int  # percent: basis points; fixed: KES
    percent: float | None  # convenience for percent discounts
    min_spend: int
    promo_code: str | None
    starts_at: datetime
    ends_at: datetime | None
    max_uses: int | None
    uses: int = 0
    is_active: bool
    is_public: bool = False
    days_mask: int | None = None
    daily_from: int | None = None
    daily_to: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _from_model(cls, obj):
        if hasattr(obj, "kind"):
            data = {k: getattr(obj, k) for k in cls.model_fields if hasattr(obj, k)}
            data["percent"] = obj.value / 100 if obj.kind == "percent" else None
            return data
        return obj


class DiscountIn(Input):
    """For percent discounts send `percent` (e.g. 15 or 12.5); for fixed send `amount` (KES)."""

    scope: Literal["item", "order"]
    product_id: uuid.UUID | None = None
    kind: Literal["percent", "fixed"]
    percent: float | None = Field(None, gt=0, le=100)
    amount: Money | None = None
    min_spend: Money = 0
    promo_code: PromoCode | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    max_uses: int | None = Field(None, ge=1, le=1_000_000)
    is_active: bool = True
    is_public: bool = False
    # Happy hour, Kenya time: weekdays bitmask Mon = 1 ... Sun = 64, and a daily window
    # in minutes from midnight (15:00-17:00 = 900-1020). Leave out for every day / all day.
    days_mask: int | None = Field(None, ge=1, le=127)
    daily_from: int | None = Field(None, ge=0, le=1439)
    daily_to: int | None = Field(None, ge=1, le=1440)

    @model_validator(mode="after")
    def _consistent(self):
        if (self.daily_from is None) != (self.daily_to is None):
            raise ValueError("Give both a start and an end time, or neither")
        if self.daily_from is not None and self.daily_to <= self.daily_from:
            raise ValueError("The happy hour must end after it starts (same day)")
        if (self.scope == "item") != (self.product_id is not None):
            raise ValueError("Item discounts need a product; order discounts must not have one")
        if self.kind == "percent" and (self.percent is None or self.amount is not None):
            raise ValueError("Percent discounts take 'percent' only")
        if self.kind == "fixed" and (self.amount is None or self.amount <= 0 or self.percent):
            raise ValueError("Fixed discounts take a positive 'amount' only")
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("The end must be after the start")
        if self.max_uses is not None and self.promo_code is None:
            raise ValueError("A total use limit only applies to promo codes")
        return self


class DiscountPatch(Input):
    """Terms of a discount are fixed once created (orders refer to it); only its dates, limit
    and on/off switch can change. Create a new discount to change the amount."""

    starts_at: datetime | None = None
    ends_at: datetime | None = None
    max_uses: int | None = Field(None, ge=1, le=1_000_000)
    is_active: bool | None = None
    is_public: bool | None = None


class OfferOut(Schema):
    id: uuid.UUID
    title: str
    image_url: str | None = None
    product_id: uuid.UUID | None
    discount_id: uuid.UUID | None
    starts_at: datetime
    ends_at: datetime | None
    sort_order: int


class OfferIn(Input):
    title: Annotated[str, Field(min_length=2, max_length=120)]
    image_key: str | None = Field(None, max_length=200)
    product_id: uuid.UUID | None = None
    discount_id: uuid.UUID | None = None
    starts_at: datetime
    ends_at: datetime | None = None
    sort_order: int = Field(0, ge=0, le=10_000)

    @model_validator(mode="after")
    def _dates(self):
        if self.ends_at is not None and self.ends_at <= self.starts_at:
            raise ValueError("The end must be after the start")
        return self


class OfferPatch(Input):
    title: Annotated[str, Field(min_length=2, max_length=120)] | None = None
    image_key: str | None = Field(None, max_length=200)
    product_id: uuid.UUID | None = None
    discount_id: uuid.UUID | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    sort_order: int | None = Field(None, ge=0, le=10_000)


# --- Hotel settings ---------------------------------------------------------------------------


class DayHours(Input):
    weekday: int = Field(ge=0, le=6)  # 0 = Monday
    opens_at: time
    closes_at: time

    @model_validator(mode="after")
    def _not_equal(self):
        if self.opens_at == self.closes_at:
            raise ValueError("Opening and closing times cannot be the same")
        return self


class HotelSettingsOut(Schema):
    name: str
    slug: str | None = None
    kind: str = "hotel"
    phone: str
    till_number: str
    till_name: str | None = None
    verified: bool = False
    cash_pickup_enabled: bool
    accepting_orders: bool
    busy_extra_minutes: int = 0
    status: str
    accent_color: str | None
    cover_url: str | None
    hours: list[DayHours]
    lat: float | None = None
    lng: float | None = None


class HotelSettingsIn(Input):
    # Identity, editable by the hotel admin; every change is audit-logged.
    name: str | None = Field(None, min_length=2, max_length=120)
    phone: Phone | None = None
    till_number: str | None = Field(None, pattern=r"^\d{5,10}$")
    cash_pickup_enabled: bool | None = None
    accepting_orders: bool | None = None
    busy_extra_minutes: int | None = Field(None, ge=0, le=90)
    accent_color: str | None = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    cover_image_key: str | None = Field(None, max_length=200)
    hours: list[DayHours] | None = Field(None, max_length=7)  # replaces all days; missing = closed
    lat: float | None = Field(None, ge=-90, le=90)  # hotel location (rider pickup point)
    lng: float | None = Field(None, ge=-180, le=180)

    @model_validator(mode="after")
    def _unique_days(self):
        if self.hours is not None and len({h.weekday for h in self.hours}) != len(self.hours):
            raise ValueError("Each weekday can appear once")
        if ("lat" in self.model_fields_set) != ("lng" in self.model_fields_set):
            raise ValueError("Send latitude and longitude together")
        if (self.lat is None) != (self.lng is None):
            raise ValueError("Set both latitude and longitude, or neither")
        if self.lat is not None and self.lng is not None:
            if not (KENYA_LAT[0] <= self.lat <= KENYA_LAT[1] and KENYA_LNG[0] <= self.lng <= KENYA_LNG[1]):
                raise ValueError("That location is outside Kenya. Check the latitude and longitude (latitude first).")
        return self


# --- Public -----------------------------------------------------------------------------------


class PublicHotel(Schema):
    slug: str
    name: str
    kind: str = "hotel"  # "liquor" = a liquor store: 18+ only
    phone: str
    accent_color: str | None
    cover_url: str | None
    is_open: bool
    state: str
    closes_at: datetime | None
    opens_at: datetime | None
    cash_pickup_enabled: bool
    verified: bool = False  # checked by the Chakula team
    till_name: str | None = None  # the name M-Pesa shows for the Till
    lat: float | None = None
    lng: float | None = None
    busy_extra_minutes: int = 0  # already included in prep_minutes; lets the app show a "busy" badge
    prep_minutes: int = 15  # typical (median) prep time of its dishes, for time estimates
    rating: float | None = None  # average stars; None until rated
    rating_count: int = 0
    # Only when the customer's location was sent: straight-line km, and whether it is beyond
    # delivery range (pickup or eat in only).
    distance_km: float | None = None
    pickup_only: bool = False


class MenuOption(Schema):
    id: uuid.UUID
    group_name: str
    name: str
    price_delta: int


class MenuProduct(Schema):
    id: uuid.UUID
    name: str
    description: str
    price: int
    prep_minutes: int
    is_sold_out: bool
    image_url: str | None
    thumb_url: str | None
    options: list[MenuOption]
    discount_price: int | None = None  # unit price after the best automatic item discount


class MenuCategory(Schema):
    id: uuid.UUID
    name: str
    available_from: time | None
    available_to: time | None
    products: list[MenuProduct]


class Menu(Schema):
    hotel: PublicHotel
    categories: list[MenuCategory]


class SearchHit(Schema):
    hotel_slug: str
    hotel_name: str
    product_id: uuid.UUID
    name: str
    category: str
    price: int
    is_sold_out: bool
    thumb_url: str | None


class PublicOffer(Schema):
    id: uuid.UUID
    hotel_slug: str
    hotel_name: str
    title: str
    image_url: str | None
    product_id: uuid.UUID | None
    ends_at: datetime | None


class PublicPromo(Schema):
    """A coupon card on the hotel's page: the code and what it is worth."""

    code: str
    worth: str  # "10% off your order over KES 500"
    ends_at: datetime | None
