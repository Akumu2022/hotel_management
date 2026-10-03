from pydantic import Field

from app.schemas.catalogue import Input

MpesaCode = Field(pattern=r"^[A-Za-z0-9]{8,12}$", description="M-Pesa transaction code")


class SettlementIn(Input):
    """The hotel sent money to the platform's M-Pesa number."""

    mpesa_code: str = MpesaCode
    amount: int = Field(strict=True, gt=0, le=10_000_000)


class ConfirmIn(Input):
    # What the platform's M-Pesa SMS shows, when the hotel typed a different amount.
    amount: int | None = Field(None, strict=True, gt=0, le=10_000_000)


class RejectIn(Input):
    note: str = Field(min_length=2, max_length=200)


class PayoutIn(Input):
    mpesa_code: str = MpesaCode
    amount: int = Field(strict=True, gt=0, le=10_000_000)
