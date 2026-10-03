"""Keyset (cursor) pagination on (created_at, id)."""

import base64
import uuid
from datetime import datetime

from sqlalchemy import Select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError

MAX_LIMIT = 100


def _encode(created_at: datetime, id_: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{created_at.isoformat()}|{id_}".encode()).decode()


def _decode(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        ts, id_ = base64.urlsafe_b64decode(cursor.encode()).decode().split("|")
        return datetime.fromisoformat(ts), uuid.UUID(id_)
    except ValueError:
        raise AppError(400, "bad_cursor", "Invalid cursor") from None


async def paginate(
    session: AsyncSession, stmt: Select, model, cursor: str | None, limit: int
) -> tuple[list, str | None]:
    """Newest first. Returns (rows, next_cursor)."""
    limit = max(1, min(limit, MAX_LIMIT))
    if cursor:
        ts, id_ = _decode(cursor)
        stmt = stmt.where(or_(model.created_at < ts, and_(model.created_at == ts, model.id < id_)))
    stmt = stmt.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    if len(rows) <= limit:
        return rows, None
    rows = rows[:limit]
    return rows, _encode(rows[-1].created_at, rows[-1].id)
