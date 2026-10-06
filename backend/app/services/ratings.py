"""Customer ratings: 1-5 stars for the hotel on every finished order, and for the rider on
deliveries. One rating per order, from the tracking link (customers have no login)."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Order, Rating

FINISHED = ("delivered", "collected")
# Ranking uses a damped average so one early 5-star review doesn't top the list: each hotel
# starts as if it had PRIOR_COUNT ratings of PRIOR_STARS.
PRIOR_STARS, PRIOR_COUNT = 4.0, 5


@dataclass(frozen=True)
class Stars:
    average: float | None  # None until the first rating
    count: int

    @property
    def rank_score(self) -> float:
        total = (self.average or 0) * self.count + PRIOR_STARS * PRIOR_COUNT
        return total / (self.count + PRIOR_COUNT)


async def submit(
    session: AsyncSession,
    order: Order,
    *,
    hotel_stars: int,
    rider_stars: int | None,
    comment: str | None,
) -> None:
    if order.status not in FINISHED:
        raise AppError(409, "not_finished", "You can rate once you have your food")
    if rider_stars is not None and order.rider_id is None:
        rider_stars = None  # pickup / eat in: no rider to rate
    if order.rider_id is not None and rider_stars is None:
        raise AppError(422, "rate_rider", "Please rate the rider too")
    comment = " ".join((comment or "").split())[:500] or None
    added = await session.scalar(
        insert(Rating)
        .values(
            order_id=order.id,
            hotel_id=order.hotel_id,
            rider_id=order.rider_id if rider_stars is not None else None,
            hotel_stars=hotel_stars,
            rider_stars=rider_stars,
            comment=comment,
        )
        .on_conflict_do_nothing()
        .returning(Rating.id)
    )
    if added is None:
        raise AppError(409, "already_rated", "You already rated this order. Thank you!")


async def is_rated(session: AsyncSession, order_id: uuid.UUID) -> bool:
    return (await session.scalar(select(Rating.id).where(Rating.order_id == order_id))) is not None


async def hotel_stars(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, Stars]:
    rows = await session.execute(
        select(Rating.hotel_id, func.avg(Rating.hotel_stars), func.count())
        .where(Rating.hotel_id.in_(ids))
        .group_by(Rating.hotel_id)
    )
    found = {h: Stars(round(float(a), 1), n) for h, a, n in rows}
    return {i: found.get(i, Stars(None, 0)) for i in ids}


async def rider_stars(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, Stars]:
    rows = await session.execute(
        select(Rating.rider_id, func.avg(Rating.rider_stars), func.count())
        .where(Rating.rider_id.in_(ids))
        .group_by(Rating.rider_id)
    )
    found = {r: Stars(round(float(a), 1), n) for r, a, n in rows}
    return {i: found.get(i, Stars(None, 0)) for i in ids}
