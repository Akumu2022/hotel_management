import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from app.schemas.catalogue import Input
from app.schemas.common import Phone, Schema

NationalId = Annotated[str, Field(pattern=r"^\d{6,9}$")]  # Kenyan ID / Maisha numbers
FullName = Annotated[str, Field(min_length=5, max_length=120)]


def _two_names(v: str | None) -> str | None:
    if v is None:
        return v
    v = " ".join(v.split())
    if len(v.split(" ")) < 2:
        raise ValueError("Enter the full name as on the ID (at least two names)")
    return v


class RiderRegisterIn(Input):
    name: FullName
    phone: Phone
    password: str = Field(min_length=8, max_length=200)
    national_id: NationalId
    next_of_kin: FullName
    next_of_kin_phone: Phone
    residence_area: str = Field(min_length=3, max_length=200)

    _names = field_validator("name", "next_of_kin")(_two_names)


class RiderDetailsIn(Input):
    """Edit while the application is a draft or was rejected."""

    name: FullName | None = None
    national_id: NationalId | None = None
    next_of_kin: FullName | None = None
    next_of_kin_phone: Phone | None = None
    residence_area: str | None = Field(None, min_length=3, max_length=200)

    _names = field_validator("name", "next_of_kin")(_two_names)

    @model_validator(mode="after")
    def _no_nulls(self):
        if any(getattr(self, f) is None for f in self.model_fields_set):
            raise ValueError("Fields can't be emptied")
        return self


class SubmitIn(Input):
    consent: bool


class ReviewIn(Input):
    action: Literal["approve", "reject", "suspend", "reinstate"]
    note: str | None = Field(None, max_length=300)


class RiderOut(Schema):
    id: uuid.UUID
    name: str
    phone: str
    national_id: str
    next_of_kin: str
    next_of_kin_phone: str | None
    residence_area: str | None
    photos: dict[str, bool]  # which KYC photos are uploaded
    photo_url: str | None  # public small photo from the selfie
    kyc_status: str
    kyc_note: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    reviewed_by_name: str | None = None
    is_online: bool
    created_at: datetime
    rating: float | None = None  # average stars from customers
    rating_count: int = 0
