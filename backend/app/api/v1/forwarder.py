"""SMS forwarder (M8, DECISIONS D26): the Till phone app's endpoints, and pairing screens."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import Field, ValidationError
from sqlalchemy import select

from app.api.deps import HotelAdmin, HotelStaff, Session, SuperAdmin
from app.core.errors import AppError, not_found
from app.core.ratelimit import limit
from app.core.time import utcnow
from app.models import Hotel
from app.schemas.catalogue import Input
from app.services import audit, forwarder

device = APIRouter(prefix="/forwarder", tags=["forwarder"])
hotel = APIRouter(prefix="/hotel/forwarder", tags=["forwarder"])
admin = APIRouter(prefix="/admin/forwarder", tags=["forwarder"])


class PairIn(Input):
    code: str = Field(min_length=8, max_length=12)
    label: str = Field("Till phone", max_length=80)
    app_version: str | None = Field(None, max_length=20)


class SmsIn(Input):
    id: str = Field(min_length=8, max_length=64)
    sender: str = Field(max_length=40)
    body: str = Field(min_length=1, max_length=2000)
    received_at: int = Field(description="Unix milliseconds")


class SmsBatchIn(Input):
    messages: list[SmsIn] = Field(max_length=100)


class HeartbeatIn(Input):
    app_version: str | None = Field(None, max_length=20)
    battery: int | None = Field(None, ge=0, le=100)
    charging: bool | None = None
    pending: int | None = Field(None, ge=0, le=100_000)
    sms_permission: bool | None = None
    android: str | None = Field(None, max_length=20)
    last_error: str | None = Field(None, max_length=200)


class AdminPairingIn(Input):
    hotel_id: uuid.UUID


def _parse(model, body: bytes):
    try:
        return model.model_validate_json(body or b"{}")
    except ValidationError as e:
        raise AppError(422, "validation_error", e.errors()[0]["msg"]) from None


# --- The phone -----------------------------------------------------------------------------------


@device.post("/pair", dependencies=[Depends(limit("forwarder_pair", 10))])
async def pair(body: PairIn, session: Session):
    now = utcnow()
    d, secret, h = await forwarder.pair(
        session, body.code, label=body.label, app_version=body.app_version, now=now
    )
    await audit.log(
        session,
        actor_id=None,
        action="forwarder.pair",
        target_type="forwarder_device",
        target_id=d.id,
        details={"hotel_id": str(h.id), "label": d.label},
    )
    await session.commit()
    return {
        "device_id": str(d.id),
        "secret": secret.hex(),
        "hotel_name": h.name,
        "till_number": h.till_number,
        "server_time": int(now.timestamp()),
    }


@device.post("/sms")
async def sms(request: Request, session: Session):
    raw = await request.body()
    now = utcnow()
    d = await forwarder.authenticate(session, request.headers, raw, now)
    batch = _parse(SmsBatchIn, raw)
    messages = [
        forwarder.Incoming(
            id=m.id,
            sender=m.sender,
            body=m.body,
            received_at=datetime.fromtimestamp(m.received_at / 1000, UTC),
        )
        for m in batch.messages
    ]
    done = await forwarder.ingest(session, d, messages, now)
    await session.commit()
    return {"accepted": done}


@device.post("/heartbeat")
async def heartbeat(request: Request, session: Session):
    raw = await request.body()
    now = utcnow()
    d = await forwarder.authenticate(session, request.headers, raw, now)
    body = _parse(HeartbeatIn, raw)
    report = body.model_dump(exclude={"app_version"}, exclude_none=True)
    await forwarder.heartbeat(session, d, report, body.app_version, now)
    await session.commit()
    return {"ok": True, "hotel_name": (await session.get(Hotel, d.hotel_id)).name}


# --- Hotel admin ---------------------------------------------------------------------------------


@hotel.get("")
async def my_phones(user: HotelStaff, session: Session):
    """Cashiers see it too: when the phone is down, they confirm payments by hand."""
    now = utcnow()
    rows = await forwarder.active_devices(session, user.hotel_id)
    return {"devices": [forwarder.device_out(d, now, name) for d, name in rows]}


@hotel.post("/pairing", status_code=201)
async def new_pairing(user: HotelAdmin, session: Session):
    code, expires = await forwarder.create_pairing(session, user.hotel_id, user.id, utcnow())
    await session.commit()
    return {"code": code, "expires_at": expires}


@hotel.delete("/{device_id}", status_code=204)
async def unpair(device_id: uuid.UUID, user: HotelAdmin, session: Session):
    await forwarder.revoke(session, device_id, user.hotel_id, utcnow())
    await session.commit()


# --- Super admin ---------------------------------------------------------------------------------


@admin.get("")
async def all_phones(_: SuperAdmin, session: Session):
    now = utcnow()
    rows = await forwarder.active_devices(session)
    paired = {d.hotel_id for d, _ in rows}
    hotels = (await session.execute(select(Hotel).order_by(Hotel.name))).scalars().all()
    return {
        "devices": [forwarder.device_out(d, now, name) for d, name in rows],
        "unpaired_hotels": [
            {"id": str(h.id), "name": h.name} for h in hotels if h.id not in paired
        ],
    }


@admin.post("/pairing", status_code=201)
async def admin_pairing(body: AdminPairingIn, user: SuperAdmin, session: Session):
    if await session.get(Hotel, body.hotel_id) is None:
        raise not_found("Hotel not found")
    code, expires = await forwarder.create_pairing(session, body.hotel_id, user.id, utcnow())
    await session.commit()
    return {"code": code, "expires_at": expires}


@admin.delete("/{device_id}", status_code=204)
async def admin_unpair(device_id: uuid.UUID, user: SuperAdmin, session: Session):
    d = await forwarder.revoke(session, device_id, None, utcnow())
    await audit.log(
        session,
        actor_id=user.id,
        action="forwarder.unpair",
        target_type="forwarder_device",
        target_id=d.id,
        details={},
    )
    await session.commit()
