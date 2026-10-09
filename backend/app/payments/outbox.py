from sqlalchemy.ext.asyncio import AsyncSession

from app.payments.models import OutboxEvent


def publish(session: AsyncSession, topic: str, payload: dict) -> None:
    """Written in the caller's transaction, so an event exists only if the money move does."""
    session.add(OutboxEvent(topic=topic, payload=payload))
