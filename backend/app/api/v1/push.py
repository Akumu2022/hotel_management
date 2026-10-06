"""Web Push subscriptions: a signed-in browser asks to be woken for alarms."""

from fastapi import APIRouter
from pydantic import Field
from sqlalchemy import delete, select

from app.api.deps import CurrentUserDep, Session
from app.core.config import get_config
from app.models import PushSubscription
from app.schemas.catalogue import Input
from app.services import push

router = APIRouter(prefix="/push", tags=["push"])


class Keys(Input):
    p256dh: str = Field(min_length=10, max_length=200)
    auth: str = Field(min_length=10, max_length=100)


class SubscribeIn(Input):
    endpoint: str = Field(min_length=10, max_length=1000, pattern=r"^https://")
    keys: Keys


class UnsubscribeIn(Input):
    endpoint: str = Field(min_length=10, max_length=1000)


@router.get("/config")
async def push_config():
    """Whether this server can send pushes, and the public key the browser needs."""
    return {
        "enabled": push.enabled(),
        "public_key": get_config().vapid_public_key if push.enabled() else None,
    }


@router.post("/subscribe", status_code=204)
async def subscribe(body: SubscribeIn, user: CurrentUserDep, session: Session):
    """One browser, one row. If someone else signs in on the same browser, it moves to them."""
    keys = {"p256dh": body.keys.p256dh, "auth": body.keys.auth}
    existing = await session.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == body.endpoint)
    )
    if existing is None:
        session.add(PushSubscription(user_id=user.id, endpoint=body.endpoint, keys=keys))
    else:
        existing.user_id, existing.keys = user.id, keys
    await session.commit()


@router.post("/unsubscribe", status_code=204)
async def unsubscribe(body: UnsubscribeIn, user: CurrentUserDep, session: Session):
    await session.execute(
        delete(PushSubscription).where(
            PushSubscription.endpoint == body.endpoint, PushSubscription.user_id == user.id
        )
    )
    await session.commit()
