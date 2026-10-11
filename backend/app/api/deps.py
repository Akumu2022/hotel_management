import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, TypeVar

import jwt
from fastapi import Depends, Header
from sqlalchemy import Select, event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import AppError, not_found
from app.core.security import decode_access_token
from app.models import User

Session = Annotated[AsyncSession, Depends(get_session)]
M = TypeVar("M")


@dataclass(frozen=True)
class CurrentUser:
    id: uuid.UUID
    role: str
    hotel_id: uuid.UUID | None


# Every logged-in call re-checks that the account is still active. The answer is kept for a few
# seconds per worker; any change to a user made in a worker drops its entry at once there, and the
# other workers catch up within USER_CACHE_SECONDS.
USER_CACHE_SECONDS = 5
_users: dict[uuid.UUID, tuple[float, CurrentUser]] = {}


def clear_user_cache() -> None:
    _users.clear()


@event.listens_for(User, "after_update")
@event.listens_for(User, "after_delete")
def _user_changed(_mapper, _conn, user) -> None:
    _users.pop(user.id, None)


async def current_user(
    session: Session,
    authorization: Annotated[str | None, Header()] = None,
    access_token: str | None = None,  # EventSource can't send headers: ?access_token= for SSE
) -> CurrentUser:
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    elif access_token:
        token = access_token
    else:
        raise AppError(401, "unauthorized", "Log in to continue")
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise AppError(401, "token_expired", "Session expired") from None
    except jwt.InvalidTokenError:
        raise AppError(401, "unauthorized", "Log in to continue") from None
    # The account may have been deactivated since the token was issued.
    uid = uuid.UUID(payload["sub"])
    hit = _users.get(uid)
    if hit is not None and time.monotonic() < hit[0]:
        return hit[1]
    user = await session.get(User, uid)
    if user is None or not user.is_active:
        raise AppError(401, "unauthorized", "Log in to continue")
    who = CurrentUser(id=user.id, role=user.role, hotel_id=user.hotel_id)
    _users[uid] = (time.monotonic() + USER_CACHE_SECONDS, who)
    return who


def require_roles(*roles: str) -> Callable:
    async def dep(user: Annotated[CurrentUser, Depends(current_user)]) -> CurrentUser:
        if user.role not in roles:
            raise AppError(403, "forbidden", "You do not have access to this")
        return user

    return dep


CurrentUserDep = Annotated[CurrentUser, Depends(current_user)]
SuperAdmin = Annotated[CurrentUser, Depends(require_roles("super_admin"))]
HotelStaff = Annotated[CurrentUser, Depends(require_roles("hotel_admin", "cashier"))]
HotelAdmin = Annotated[CurrentUser, Depends(require_roles("hotel_admin"))]


# --- Hotel scoping ----------------------------------------------------------------------------
# Every hotel-area query goes through these helpers, so it is always filtered by the caller's
# hotel. Another hotel's row looks exactly like a missing row: 404, never 403.


def scoped(stmt: Select, model, hotel_id: uuid.UUID) -> Select:
    return stmt.where(model.hotel_id == hotel_id)


def scoped_select(model, hotel_id: uuid.UUID) -> Select:
    return scoped(select(model), model, hotel_id)


async def get_scoped(session: AsyncSession, model: type[M], id_: uuid.UUID, hotel_id) -> M:
    row = (
        await session.execute(scoped_select(model, hotel_id).where(model.id == id_))
    ).scalar_one_or_none()
    if row is None:
        raise not_found()
    return row
