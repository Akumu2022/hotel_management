"""Staff and rider login: 15-minute JWT access tokens plus rotating refresh tokens stored hashed.
Presenting an already-rotated refresh token revokes every session of that user (token theft)."""

import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_config
from app.core.errors import AppError
from app.core.phone import normalize_phone
from app.core.security import (
    DUMMY_HASH,
    create_access_token,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.core.time import utcnow
from app.models import RefreshToken, User


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    user: User


def _invalid_login() -> AppError:
    return AppError(401, "invalid_login", "Wrong phone number or password")


async def login(session: AsyncSession, phone: str, password: str) -> TokenPair:
    try:
        phone = normalize_phone(phone)
    except ValueError:
        verify_password(DUMMY_HASH, password)
        raise _invalid_login() from None
    user = (await session.execute(select(User).where(User.phone == phone))).scalar_one_or_none()
    if user is None:
        verify_password(DUMMY_HASH, password)
        raise _invalid_login()
    if not verify_password(user.password_hash, password) or not user.is_active:
        raise _invalid_login()
    return await _issue(session, user)


async def _issue(session: AsyncSession, user: User) -> TokenPair:
    raw = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(raw),
            expires_at=utcnow() + timedelta(days=get_config().refresh_token_days),
        )
    )
    await session.flush()
    return TokenPair(create_access_token(user.id, user.role, user.hotel_id), raw, user)


class RefreshReused(Exception):
    """A revoked refresh token was presented; all the user's tokens were revoked.
    The caller must commit before returning 401 so the revocation sticks."""


async def refresh(session: AsyncSession, raw: str) -> TokenPair:
    now = utcnow()
    token_hash = hash_token(raw)
    rotated = await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(revoked_at=now)
        .returning(RefreshToken.user_id)
    )
    user_id = rotated.scalar_one_or_none()
    if user_id is None:
        existing = (
            await session.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        ).scalar_one_or_none()
        if existing is not None and existing.revoked_at is not None:
            await revoke_all(session, existing.user_id)
            raise RefreshReused()
        raise AppError(401, "invalid_refresh", "Please log in again")
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError(401, "invalid_refresh", "Please log in again")
    return await _issue(session, user)


async def logout(session: AsyncSession, raw: str) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_token(raw), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


async def revoke_all(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
