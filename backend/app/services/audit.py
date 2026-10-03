import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def log(
    session: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: str | uuid.UUID | None = None,
    details: dict | None = None,
) -> None:
    session.add(
        AuditLog(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details or {},
        )
    )
    await session.flush()
