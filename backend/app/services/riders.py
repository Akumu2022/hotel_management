"""Rider sign-up and KYC review (DECISIONS D21).

Riders register themselves; the super admin reviews every application and is the only one who
sees ID photos. Hotels never manage riders.

    draft --submit--> pending --approve--> approved --suspend--> suspended --reinstate--> approved
                         |                                                (also from pending)
                         +--reject--> rejected --edit & submit--> pending

ID photos and the selfie are stored in private storage: the static file server never serves
them, only the admin-only endpoint does. EXIF (incl. GPS) is stripped on re-encode.
"""

import io
import secrets
import uuid
from datetime import datetime
from pathlib import Path

from PIL import Image
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.errors import AppError
from app.core.security import hash_password
from app.models import Order, RiderProfile, User
from app.services import audit, events
from app.services.media import Storage, process_image

KINDS = ("id_front", "id_back", "selfie")
EDITABLE = ("draft", "rejected")
PHOTO_SIZE = 240  # public rider photo shown to customers and hotels

# Review actions: action -> (allowed from, to)
ACTIONS = {
    "approve": (("pending",), "approved"),
    "reject": (("pending",), "rejected"),
    "suspend": (("approved", "pending"), "suspended"),
    "reinstate": (("suspended",), "approved"),
}


class PrivateStorage:
    """Local folder outside the public media mount. Replaced by a private bucket at deploy."""

    def __init__(self, root: str):
        self.root = Path(root)

    def put(self, key: str, data: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


def get_private_storage() -> PrivateStorage:
    return PrivateStorage(get_config().private_media_dir)


async def register(
    session: AsyncSession,
    *,
    name: str,
    phone: str,
    password: str,
    national_id: str,
    next_of_kin: str,
    next_of_kin_phone: str,
    residence_area: str,
) -> User:
    if next_of_kin_phone == phone:
        raise AppError(
            422,
            "same_phone",
            "Next of kin needs their own phone number",
            extra={"field": "next_of_kin_phone"},
        )
    user = User(role="rider", name=name, phone=phone, password_hash=hash_password(password))
    session.add(user)
    try:
        async with session.begin_nested():
            await session.flush()
            session.add(
                RiderProfile(
                    user_id=user.id,
                    national_id=national_id,
                    mpesa_number=phone,
                    next_of_kin=next_of_kin,
                    next_of_kin_phone=next_of_kin_phone,
                    residence_area=residence_area,
                )
            )
            await session.flush()
    except IntegrityError as e:
        field = "national_id" if "national_id" in str(e.orig) else "phone"
        which = "ID number" if field == "national_id" else "phone number"
        raise AppError(
            409,
            "already_registered",
            f"That {which} is already registered",
            extra={"field": field},
        ) from None
    return user


PHOTO_LABELS = {"id_front": "ID front", "id_back": "ID back", "selfie": "selfie"}


async def apply(
    session: AsyncSession,
    private: PrivateStorage,
    public: Storage,
    *,
    photos: dict[str, bytes],
    consent: bool,
    now: datetime,
    **details,
) -> User:
    """The whole application in one request (owner, D21): details, three photos and consent.
    Nothing is created unless all of it is valid, so there are no half-finished sign-ups."""
    if not consent:
        raise AppError(
            422,
            "consent_required",
            "Tick the box to agree to the ID check",
            extra={"field": "consent"},
        )
    checked = {}
    for kind in KINDS:
        data = photos.get(kind) or b""
        if not data:
            raise AppError(
                422, "photo_missing", f"Add the {PHOTO_LABELS[kind]} photo", extra={"field": kind}
            )
        try:
            process_image(data)
        except AppError:
            raise AppError(
                422,
                "bad_photo",
                f"The {PHOTO_LABELS[kind]} photo couldn't be read. Take it again.",
                extra={"field": kind},
            ) from None
        checked[kind] = data
    user = await register(session, **details)
    p = await profile(session, user.id, lock=True)
    for kind, data in checked.items():
        save_photo(private, public, p, kind, data)
    p.consent_at = now
    p.kyc_status = "pending"
    p.submitted_at = now
    await session.flush()
    return user


async def profile(session: AsyncSession, user_id: uuid.UUID, *, lock: bool = False) -> RiderProfile:
    stmt = select(RiderProfile).where(RiderProfile.user_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    p = (await session.execute(stmt)).scalar_one_or_none()
    if p is None:
        raise AppError(404, "not_found", "Rider not found")
    return p


def _require_editable(p: RiderProfile) -> None:
    if p.kyc_status not in EDITABLE:
        raise AppError(
            409, "kyc_locked", "Your application is with the team. You can't change it now."
        )


async def update_details(session: AsyncSession, user: User, changes: dict) -> RiderProfile:
    p = await profile(session, user.id, lock=True)
    _require_editable(p)
    if "name" in changes:
        user.name = changes.pop("name")
    for key, value in changes.items():
        setattr(p, key, value)
    try:
        await session.flush()
    except IntegrityError:
        raise AppError(409, "already_registered", "That ID number is already registered") from None
    return p


def save_photo(
    private: PrivateStorage, public: Storage, p: RiderProfile, kind: str, data: bytes
) -> None:
    if kind not in KINDS:
        raise AppError(404, "not_found", "Unknown photo")
    _require_editable(p)
    full, _ = process_image(data)  # validates, fixes rotation, strips EXIF/GPS
    stem = f"riders/{p.user_id}/{kind}-{secrets.token_urlsafe(12)}"
    private.put(f"{stem}.webp", full)
    setattr(p, f"{kind}_key", f"{stem}.webp")
    if kind == "selfie":
        img = Image.open(io.BytesIO(full))
        img.thumbnail((PHOTO_SIZE, PHOTO_SIZE))
        out = io.BytesIO()
        img.save(out, "WEBP", quality=75)
        key = f"riders/{p.user_id}/photo-{secrets.token_urlsafe(12)}.webp"
        public.put(key, out.getvalue(), "image/webp")
        p.photo_key = key


async def submit(session: AsyncSession, user_id: uuid.UUID, *, consent: bool, now: datetime):
    p = await profile(session, user_id, lock=True)
    if p.kyc_status == "pending":
        return p  # repeat tap
    _require_editable(p)
    missing = [k.replace("_", " ") for k in KINDS if getattr(p, f"{k}_key") is None]
    if missing:
        raise AppError(422, "photos_missing", f"Add your {', '.join(missing)} photo first")
    if not p.next_of_kin_phone or not p.residence_area:
        raise AppError(422, "details_missing", "Fill in your next of kin and where you live")
    if not consent:
        raise AppError(422, "consent_required", "Tick the box to agree to the ID check")
    p.consent_at = now
    p.kyc_status = "pending"
    p.kyc_note = None
    p.submitted_at = now
    await session.flush()
    return p


async def review(
    session: AsyncSession,
    rider_id: uuid.UUID,
    action: str,
    note: str | None,
    admin_id: uuid.UUID,
    now: datetime,
) -> RiderProfile:
    if action not in ACTIONS:
        raise AppError(422, "bad_action", "Choose approve, reject, suspend or reinstate")
    allowed, target = ACTIONS[action]
    p = await profile(session, rider_id, lock=True)
    if p.kyc_status == target:
        return p  # repeat tap
    if p.kyc_status not in allowed:
        raise AppError(409, "wrong_status", f"This rider is {p.kyc_status}")
    if action in ("reject", "suspend") and not (note and note.strip()):
        raise AppError(422, "reason_required", "Give the rider a reason")
    previous = p.kyc_status
    p.kyc_status = target
    p.kyc_note = note.strip() if note and action in ("reject", "suspend") else None
    p.reviewed_by = admin_id
    p.reviewed_at = now
    if target != "approved":
        p.is_online = False
        await _release_jobs(session, rider_id)
    await audit.log(
        session,
        actor_id=admin_id,
        action=f"rider.{action}",
        target_type="rider",
        target_id=rider_id,
        details={"from": previous, "to": target, "note": p.kyc_note},
    )
    await session.flush()
    return p


async def _release_jobs(session: AsyncSession, rider_id: uuid.UUID) -> None:
    """Jobs not yet collected go back to the open pool (and ring other riders); a job already
    on the road stays with the rider and shows on the admin's dispatch board."""
    orders = (
        (
            await session.execute(
                select(Order)
                .where(
                    Order.rider_id == rider_id, Order.status.in_(("accepted", "preparing", "ready"))
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for order in orders:
        order.rider_id = None
        order.assigned_at = None
        order.rider_seen_at = None
        events.order_changed(session, order, {"released": True})


async def require_approved(session: AsyncSession, user_id: uuid.UUID) -> RiderProfile:
    p = await profile(session, user_id)
    if p.kyc_status != "approved":
        raise AppError(403, "not_approved", "Your rider account isn't approved yet")
    return p
