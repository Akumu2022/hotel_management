import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.catalogue import Input
from app.schemas.common import Schema


class CodeIn(Input):
    code: str = Field(min_length=8, max_length=20)


class ConfirmIn(Input):
    code: str = Field(min_length=8, max_length=20)
    amount: int = Field(gt=0, le=1_000_000, strict=True)
    paid_at: datetime | None = None  # time on the M-Pesa message, if the cashier enters it


class OutcomeOut(Schema):
    result: str
    order_status: str
    message: str


class HotelOrderOut(Schema):
    id: uuid.UUID
    code: str
    platform_bonus: int = 0  # paid to the hotel by the platform on its statement (D19)
    rider_name: str | None = None
    rider_phone: str | None = None
    rider_photo_url: str | None = None
    fee_with_food: bool = False  # option A instant: hand the rider fee over with the food
    fee_handed: bool = False
    status: str
    type: str
    payment_method: str
    rider_fee_mode: str
    customer_name: str
    customer_phone: str
    till_amount: int
    rider_fee: int
    distance_km: float | None
    customer_trans_code: str | None
    items: list[str]
    created_at: datetime
    expires_at: datetime | None
    paid_at: datetime | None
    accepted_at: datetime | None = None
    ready_at: datetime | None = None
    prep_minutes: int | None = None
    landmark: str | None = None
    reason: str | None = None


class ReviewOut(Schema):
    id: uuid.UUID
    type: str
    status: str
    reason: str
    order_id: uuid.UUID | None
    order_code: str | None = None
    hotel_name: str | None = None
    hotel_phone: str | None = None
    amount: int | None = None  # the payment's amount, if any
    trans_code: str | None = None
    order_total: int | None = None
    actions: list[str]
    resolution: str | None
    created_at: datetime
    resolved_at: datetime | None


class ResolveIn(Input):
    action: str = Field(max_length=30)
    order_code: str | None = Field(None, max_length=13)  # for "match_order"


class RefundOut(Schema):
    id: uuid.UUID
    order_id: uuid.UUID
    order_code: str | None = None
    customer_phone: str | None = None
    amount: int
    reason: str
    status: str
    mpesa_code: str | None
    created_at: datetime
    sent_at: datetime | None


class RefundIn(Input):
    """Hotel admin approves a refund (e.g. a missing item). Parts in KES."""

    order_id: uuid.UUID
    food: int = Field(0, ge=0, strict=True)
    service_fee: int = Field(0, ge=0, strict=True)
    rider_fee: int = Field(0, ge=0, strict=True)
    reason: str = Field(min_length=3, max_length=300)
    refund_id: uuid.UUID | None = None  # client-generated, makes a repeat tap safe


class RefundSentIn(Input):
    mpesa_code: str = Field(min_length=8, max_length=20)


class TestPaymentIn(Input):
    """Admin simulator for an M-Pesa payment arriving on a Till (stands in for M8)."""

    till_number: str = Field(pattern=r"^\d{5,10}$")
    code: str = Field(min_length=8, max_length=20)
    amount: int = Field(gt=0, le=1_000_000, strict=True)
    paid_at: datetime | None = None
    phone_digits: str | None = Field(None, max_length=16)
    kind: Literal["payment", "reversal"] = "payment"


class TestSmsIn(Input):
    """Paste a real Till SMS: it goes through the parser and matching like an M8 message."""

    till_number: str = Field(pattern=r"^\d{5,10}$")
    raw_text: str = Field(min_length=10, max_length=1000)


class AcceptIn(Input):
    prep_minutes: int = Field(ge=1, le=180, strict=True)


class CancelIn(Input):
    reason: Literal["ran_out", "kitchen_problem", "customer_asked", "other"]
    note: str | None = Field(None, max_length=200)


class RejectIn(Input):
    reason: Literal["sold_out", "too_busy", "closing", "cannot_deliver", "other"]
    note: str | None = Field(None, max_length=200)
