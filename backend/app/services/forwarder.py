"""SMS forwarder: the Android app on each hotel's Till phone sends M-Pesa
messages here, so payments confirm themselves.

Pairing: a hotel admin shows a one-time code (8 letters, 15 minutes). The app sends it once and
gets its device ID and a signing secret. Pairing a new phone for a Till unpairs the old one.

Every later request is signed:

    X-Device-Id: <uuid>   X-Timestamp: <unix seconds>   X-Nonce: <random, 16-64 chars>
    X-Signature: hex HMAC-SHA256(secret, "<timestamp>\\n<nonce>\\n<sha256 hex of the body>")

Requests older or newer than 5 minutes, a reused nonce, or a revoked phone are refused.

Messages: each has the app's own stable ID. The server stores the raw text once (dispute
evidence), parses it, and runs it through the same matching as everything else. A message seen
twice (receiver + inbox rescan, or a retry) is acknowledged and ignored, so the app can resend
freely until it gets an acknowledgement. One bad message never blocks the rest.
"""

import hashlib
import hmac
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.errors import AppError
from app.models import DeviceNonce, ForwarderDevice, ForwarderPairing, Hotel, SmsMessage
from app.services import events, payments, sms_parser

log = logging.getLogger("app.forwarder")

PAIRING_TTL = timedelta(minutes=15)
CLOCK_SKEW = timedelta(minutes=5)
NONCE_KEEP = timedelta(hours=1)
# The app checks in every 15 minutes (Android's shortest periodic job). Two missed check-ins
# and a bit: the phone is off, offline, or the app was stopped.
OFFLINE_AFTER = timedelta(minutes=40)
ALPHABET = "ACDEFGHJKMNPQRTUVWXY3479"  # no look-alikes (0/O, 1/I/L, 5/S, 8/B, 2/Z, 6/G)
MPESA_SENDERS = {"MPESA", "M-PESA"}


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def normalize_pairing(raw: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())


def device_secret(device: ForwarderDevice) -> bytes:
    """The phone's signing key. `secret_encrypted` holds only a random salt ("v1:<hex>")."""
    salt = device.secret_encrypted.removeprefix("v1:")
    return hmac.new(get_config().forwarder_key.encode(), bytes.fromhex(salt), "sha256").digest()


def sign(secret: bytes, timestamp: str, nonce: str, body: bytes) -> str:
    msg = f"{timestamp}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode()
    return hmac.new(secret, msg, "sha256").hexdigest()


# --- Pairing -----------------------------------------------------------------------------------


async def create_pairing(
    session: AsyncSession, hotel_id: uuid.UUID, user_id: uuid.UUID | None, now: datetime
) -> tuple[str, datetime]:
    """A fresh one-time code, shown as XXXX-XXXX. Older unused codes for the hotel stop working."""
    await session.execute(
        update(ForwarderPairing)
        .where(ForwarderPairing.hotel_id == hotel_id, ForwarderPairing.used_at.is_(None))
        .values(expires_at=now)
    )
    code = "".join(secrets.choice(ALPHABET) for _ in range(8))
    expires = now + PAIRING_TTL
    session.add(
        ForwarderPairing(
            hotel_id=hotel_id, code_hash=_hash(code), expires_at=expires, created_by=user_id
        )
    )
    await session.flush()
    return f"{code[:4]}-{code[4:]}", expires


async def pair(
    session: AsyncSession, raw_code: str, *, label: str, app_version: str | None, now: datetime
) -> tuple[ForwarderDevice, bytes, Hotel]:
    code = normalize_pairing(raw_code)
    pairing = await session.scalar(
        select(ForwarderPairing).where(ForwarderPairing.code_hash == _hash(code)).with_for_update()
    )
    if pairing is None or pairing.used_at is not None or pairing.expires_at <= now:
        raise AppError(400, "bad_pairing_code", "That code is wrong or expired. Make a new one.")
    hotel = await session.get(Hotel, pairing.hotel_id)
    # One phone per Till: pairing a new one unpairs the old one.
    old = (
        await session.execute(
            update(ForwarderDevice)
            .where(
                ForwarderDevice.till_number == hotel.till_number,
                ForwarderDevice.revoked_at.is_(None),
            )
            .values(revoked_at=now)
            .returning(ForwarderDevice.id)
        )
    ).all()
    device = ForwarderDevice(
        hotel_id=hotel.id,
        label=(label.strip() or "Till phone")[:80],
        till_number=hotel.till_number,
        secret_encrypted="v1:" + secrets.token_hex(32),
        app_version=(app_version or "")[:20] or None,
        last_heartbeat_at=now,
        last_report={},
    )
    session.add(device)
    await session.flush()
    pairing.used_at, pairing.device_id = now, device.id
    _changed(session, hotel.id)
    log.info(
        "forwarder paired", extra={"extra_fields": {"hotel": str(hotel.id), "replaced": len(old)}}
    )
    return device, device_secret(device), hotel


async def revoke(session: AsyncSession, device_id: uuid.UUID, hotel_id: uuid.UUID | None, now):
    """Unpair a phone. `hotel_id` limits it to that hotel's phones (hotel admins)."""
    device = await session.get(ForwarderDevice, device_id)
    if device is None or (hotel_id is not None and device.hotel_id != hotel_id):
        raise AppError(404, "not_found", "Phone not found")
    if device.revoked_at is None:
        device.revoked_at = now
        _changed(session, device.hotel_id)
    return device


def _changed(session: AsyncSession, hotel_id: uuid.UUID | None) -> None:
    payload = {"type": "forwarder"}
    if hotel_id:
        events.emit(session, f"hotel:{hotel_id}", payload)
    events.emit(session, "admin", payload)


# --- Request signing ---------------------------------------------------------------------------


async def authenticate(
    session: AsyncSession, headers, body: bytes, now: datetime
) -> ForwarderDevice:
    refuse = AppError(401, "bad_signature", "Request not signed by a paired phone")
    try:
        device_id = uuid.UUID(headers.get("x-device-id", ""))
        ts = int(headers.get("x-timestamp", ""))
    except ValueError:
        raise refuse from None
    nonce = headers.get("x-nonce", "")
    signature = headers.get("x-signature", "")
    if not (16 <= len(nonce) <= 64) or not signature:
        raise refuse
    sent = datetime.fromtimestamp(ts, UTC)
    if abs(now - sent) > CLOCK_SKEW:
        raise AppError(401, "clock_skew", "The phone's clock is wrong. Set automatic time.")
    device = await session.get(ForwarderDevice, device_id)
    if device is None:
        raise refuse
    expected = sign(device_secret(device), str(ts), nonce, body)
    if not hmac.compare_digest(expected, signature.lower()):
        raise refuse
    if device.revoked_at is not None:
        raise AppError(401, "unpaired", "This phone was unpaired. Pair it again.")
    fresh = await session.scalar(
        insert(DeviceNonce)
        .values(device_id=device.id, nonce=nonce)
        .on_conflict_do_nothing()
        .returning(DeviceNonce.id)
    )
    if fresh is None:
        raise AppError(401, "replayed", "Request already used")
    return device


async def prune_nonces(session: AsyncSession, now: datetime) -> int:
    """Background job: nonces only need to outlive the 5-minute clock window."""
    result = await session.execute(
        delete(DeviceNonce).where(DeviceNonce.created_at < now - NONCE_KEEP)
    )
    return result.rowcount or 0


# --- Messages ----------------------------------------------------------------------------------


@dataclass
class Incoming:
    id: str  # the app's stable ID for this message
    sender: str
    body: str
    received_at: datetime


def is_mpesa(sender: str) -> bool:
    return re.sub(r"[^A-Z-]", "", (sender or "").upper()) in MPESA_SENDERS


async def ingest(
    session: AsyncSession, device: ForwarderDevice, messages: list[Incoming], now: datetime
) -> list[str]:
    """Store and process messages. Returns the IDs the phone may forget (all handled ones)."""
    done: list[str] = []
    for m in messages:
        if not is_mpesa(m.sender):
            done.append(m.id)  # the app only sends M-Pesa; anything else is dropped unread
            continue
        try:
            async with session.begin_nested():
                await _one(session, device, m, now)
        except Exception:  # a bug on one message must not block the queue behind it
            log.exception("forwarder message failed", extra={"extra_fields": {"id": m.id}})
            async with session.begin_nested():
                await payments.open_review(
                    session,
                    type="parse_failed",
                    hotel_id=device.hotel_id,
                    reason=f"Couldn't process an SMS from the Till phone: {m.body[:200]}",
                )
        done.append(m.id)
    device.last_sms_at = now
    if done:
        _changed(session, device.hotel_id)
    return done


async def _one(session: AsyncSession, device: ForwarderDevice, m: Incoming, now: datetime) -> None:
    parsed = sms_parser.parse(m.body)
    sms_id = await session.scalar(
        insert(SmsMessage)
        .values(
            device_id=device.id,
            message_id=f"{device.id.hex[:16]}:{m.id[:40]}",
            raw_text=m.body,
            received_at=m.received_at,
            parse_status=parsed.status,
            trans_code=parsed.code,
            amount=parsed.amount,
            sender_name=parsed.sender_name[:120] if parsed.sender_name else None,
            phone_digits=parsed.phone_digits[:16] if parsed.phone_digits else None,
            paid_at=parsed.paid_at,
        )
        .on_conflict_do_nothing()
        .returning(SmsMessage.id)
    )
    if sms_id is None:
        return  # seen before
    if parsed.status == "parsed":
        await payments.record_incoming(
            session,
            till_number=device.till_number,
            code=parsed.code,
            amount=parsed.amount,
            paid_at=parsed.paid_at,
            source="forwarder",
            phone_digits=parsed.phone_digits,
            payer_name=parsed.sender_name,
            sms_message_id=sms_id,
            now=now,
        )
    elif parsed.status == "reversal":
        await payments.record_reversal(session, parsed.code, now)
    elif parsed.status == "failed":
        await payments.open_review(
            session,
            type="parse_failed",
            hotel_id=device.hotel_id,
            sms_message_id=sms_id,
            reason=f"Unreadable M-Pesa SMS ({parsed.reason}): {m.body[:200]}",
        )


async def heartbeat(
    session: AsyncSession, device: ForwarderDevice, report: dict, app_version: str | None, now
) -> None:
    was_offline = not is_online(device, now)
    device.last_heartbeat_at = now
    device.last_report = report
    if app_version:
        device.app_version = app_version[:20]
    if was_offline or report.get("sms_permission") is False:
        _changed(session, device.hotel_id)


# --- Status ------------------------------------------------------------------------------------


def is_online(device: ForwarderDevice, now: datetime) -> bool:
    return device.last_heartbeat_at is not None and now - device.last_heartbeat_at < OFFLINE_AFTER


def device_out(device: ForwarderDevice, now: datetime, hotel_name: str | None = None) -> dict:
    r = device.last_report or {}
    problems = []
    if not is_online(device, now):
        problems.append("offline")
    if r.get("sms_permission") is False:
        problems.append("no_sms_permission")
    if (r.get("pending") or 0) > 0 and not is_online(device, now):
        problems.append("messages_waiting")
    return {
        "id": str(device.id),
        "hotel_id": str(device.hotel_id) if device.hotel_id else None,
        "hotel_name": hotel_name,
        "label": device.label,
        "till_number": device.till_number,
        "app_version": device.app_version,
        "last_heartbeat_at": device.last_heartbeat_at,
        "last_sms_at": device.last_sms_at,
        "battery": r.get("battery"),
        "charging": r.get("charging"),
        "pending": r.get("pending"),
        "sms_permission": r.get("sms_permission"),
        "online": is_online(device, now),
        "problems": problems,
        "paired_at": device.created_at,
    }


async def active_devices(session: AsyncSession, hotel_id: uuid.UUID | None = None):
    stmt = (
        select(ForwarderDevice, Hotel.name)
        .join(Hotel, Hotel.id == ForwarderDevice.hotel_id, isouter=True)
        .where(ForwarderDevice.revoked_at.is_(None))
    )
    if hotel_id is not None:
        stmt = stmt.where(ForwarderDevice.hotel_id == hotel_id)
    return (await session.execute(stmt.order_by(Hotel.name))).all()
