import uuid

from pydantic import Field

from app.schemas.common import Schema


class LoginIn(Schema):
    phone: str = Field(max_length=20)
    password: str = Field(max_length=200)


class RefreshIn(Schema):
    refresh_token: str = Field(max_length=200)


class MeOut(Schema):
    id: uuid.UUID
    role: str
    hotel_id: uuid.UUID | None
    name: str
    phone: str


class TokenOut(Schema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: MeOut
