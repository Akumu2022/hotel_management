import uuid

from pydantic import Field

from app.schemas.common import Phone, Schema


class LoginIn(Schema):
    phone: str = Field(max_length=20)
    password: str = Field(max_length=200)


class RefreshIn(Schema):
    # Browsers send the httpOnly cookie instead; other clients may still send it here.
    refresh_token: str | None = Field(None, max_length=200)


class MeOut(Schema):
    id: uuid.UUID
    role: str
    hotel_id: uuid.UUID | None
    name: str
    phone: str
    must_change_password: bool = False


class TokenOut(Schema):
    """The refresh token is never in the body: it travels only as an httpOnly cookie, so
    page scripts can't read it. The access token lasts 15 minutes and is kept in memory."""

    access_token: str
    token_type: str = "bearer"
    user: MeOut


class ChangePasswordIn(Schema):
    current_password: str = Field(max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


class TempPasswordOut(Schema):
    temp_password: str


class CashierIn(Schema):
    name: str = Field(min_length=2, max_length=120)
    phone: Phone
    password: str = Field(min_length=8, max_length=200)


class StaffActiveIn(Schema):
    is_active: bool
