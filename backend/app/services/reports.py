"""Dashboard reports for hotel admins and the super admin.

Everything is worked out from the append-only ledger, so the numbers always agree with the
weekly statements. Dates are Kenya days; a range is inclusive of both ends.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import Select, and_, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models import Hotel, LedgerEntry, Order, OrderItem, Product

EAT = timedelta(hours=3)
MAX_DAYS = 366
GONE = ("cancelled", "rejected", "expired")
RECEIVED = ("till_received", "cash_received")
GROUPS = ("day", "week", "month")

# Signed contributions to each total.
EARNINGS = {  # what the platform earns
    "commission": 1,
    "commission_reversal": -1,
    "service_fee": 1,
    "service_fee_reversal": -1,
    "bonus_credit": -1,
    "bonus_credit_reversal": 1,
}


@dataclass(frozen=True)
class Range:
    start: datetime  # UTC
    end: datetime  # UTC, exclusive

    @classmethod
    def of(cls, first: date, last: date) -> "Range":
        if last < first:
            raise AppError(422, "bad_range", "The end date is before the start date")
        if (last - first).days >= MAX_DAYS:
            raise AppError(422, "bad_range", f"Choose at most {MAX_DAYS} days")
        start = datetime.combine(first, time(), tzinfo=UTC) - EAT
        end = datetime.combine(last + timedelta(days=1), time(), tzinfo=UTC) - EAT
        return cls(start, end)


def _local(col):
    """A UTC timestamptz column as Kenya wall-clock time."""
    return func.timezone("UTC", col) + literal(EAT)


def _entries(r: Range, hotel_id: uuid.UUID | None) -> Select:
    stmt = select(LedgerEntry).where(
        LedgerEntry.created_at >= r.start, LedgerEntry.created_at < r.end
    )
    if hotel_id is not None:
        stmt = stmt.join(Order, Order.id == LedgerEntry.order_id).where(Order.hotel_id == hotel_id)
    return stmt


def _sum(entry_type: str):
    return func.coalesce(
        func.sum(case((LedgerEntry.entry_type == entry_type, LedgerEntry.amount), else_=0)), 0
    )


def _earnings():
    return func.coalesce(
        func.sum(
            case(
                *[
                    (LedgerEntry.entry_type == t, LedgerEntry.amount * sign)
                    for t, sign in EARNINGS.items()
                ],
                else_=0,
            )
        ),
        0,
    )


def _orders_received():
    return func.count(
        func.distinct(case((LedgerEntry.entry_type.in_(RECEIVED), LedgerEntry.order_id)))
    )


def _totals_columns():
    return (
        _orders_received().label("orders"),
        _sum("till_received").label("mpesa"),
        _sum("cash_received").label("cash"),
        _sum("refund").label("refunds"),
        (_sum("commission") - _sum("commission_reversal")).label("commission"),
        (_sum("service_fee") - _sum("service_fee_reversal")).label("service_fee"),
        (_sum("bonus_credit") - _sum("bonus_credit_reversal")).label("bonuses"),
        _earnings().label("earnings"),
    )


TOTAL_KEYS = (
    "orders",
    "mpesa",
    "cash",
    "refunds",
    "commission",
    "service_fee",
    "bonuses",
    "earnings",
)


def _row(row) -> dict:
    d = {k: int(row._mapping[k] or 0) for k in TOTAL_KEYS}
    d["received"] = d["mpesa"] + d["cash"]
    d["net_received"] = d["received"] - d["refunds"]
    return d


async def summary(
    session: AsyncSession,
    r: Range,
    *,
    hotel_id: uuid.UUID | None,
    group: str,
) -> dict:
    if group not in GROUPS:
        raise AppError(422, "bad_group", "Group by day, week or month")
    q = _entries(r, hotel_id).with_only_columns(*_totals_columns())
    totals = _row((await session.execute(q)).one())

    period = func.date_trunc(group, _local(LedgerEntry.created_at)).label("period")
    series_q = (
        _entries(r, hotel_id)
        .with_only_columns(period, *_totals_columns())
        .group_by(period)
        .order_by(period)
    )
    series = [
        {"period": row.period.date().isoformat(), **_row(row)}
        for row in (await session.execute(series_q)).all()
    ]

    # Orders that brought money in during the range and still stand (not refunded away).
    paid_orders = (
        _entries(r, hotel_id)
        .where(LedgerEntry.entry_type.in_(RECEIVED))
        .with_only_columns(LedgerEntry.order_id)
        .distinct()
        .subquery()
    )
    live = and_(Order.id.in_(select(paid_orders.c.order_id)), Order.status.not_in(GONE))

    top_q = (
        select(
            OrderItem.name_snapshot.label("name"),
            func.sum(OrderItem.quantity).label("quantity"),
            func.sum(OrderItem.line_total).label("sales"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(live)
        .group_by(OrderItem.name_snapshot)
        .order_by(func.sum(OrderItem.line_total).desc())
        .limit(10)
    )
    top_items = [
        {"name": n, "quantity": int(qty), "sales": int(s)}
        for n, qty, s in (await session.execute(top_q)).all()
    ]

    # Every item sold, most to least, for planning (the top ten above is just the head of this).
    rank_q = (
        select(
            OrderItem.name_snapshot,
            func.sum(OrderItem.quantity),
            func.sum(OrderItem.line_total),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(live)
        .group_by(OrderItem.name_snapshot)
        .order_by(func.sum(OrderItem.quantity).desc(), OrderItem.name_snapshot)
        .limit(500)
    )
    item_ranking = [
        {"name": n, "quantity": int(qty), "sales": int(sales)}
        for n, qty, sales in (await session.execute(rank_q)).all()
    ]
    # Menu items that did not sell at all in the period (one hotel at a time).
    unsold: list[str] = []
    if hotel_id is not None:
        sold = {i["name"] for i in item_ranking}
        names = (
            await session.scalars(
                select(Product.name)
                .where(Product.hotel_id == hotel_id, Product.is_archived.is_(False))
                .order_by(Product.name)
            )
        ).all()
        unsold = [n for n in names if n not in sold]

    hour = func.extract("hour", _local(Order.created_at)).label("hour")
    hours_q = select(hour, func.count(), func.coalesce(func.sum(Order.food_net), 0)).where(live)
    hours_q = hours_q.group_by(hour)
    by_hour = [0] * 24
    by_hour_sales = [0] * 24
    for h, n, sales in (await session.execute(hours_q)).all():
        by_hour[int(h)] = int(n)
        by_hour_sales[int(h)] = int(sales)

    # Monday = 0 ... Sunday = 6 (Kenya days).
    dow = (func.extract("isodow", _local(Order.created_at)) - 1).label("dow")
    dow_q = select(dow, func.count(), func.coalesce(func.sum(Order.food_net), 0)).where(live)
    dow_q = dow_q.group_by(dow)
    by_weekday = [{"orders": 0, "sales": 0} for _ in range(7)]
    for d, n, sales in (await session.execute(dow_q)).all():
        by_weekday[int(d)] = {"orders": int(n), "sales": int(sales)}

    food_q = select(
        func.coalesce(func.sum(Order.food_net), 0),
        func.count(),
        func.count().filter(Order.type == "delivery"),
    ).where(live)
    food, count, deliveries = (int(v) for v in (await session.execute(food_q)).one())
    totals["food_sales"] = food
    totals["average_order"] = food // count if count else 0
    totals["deliveries"] = deliveries
    totals["pickups"] = count - deliveries

    out = {
        "totals": totals,
        "series": series,
        "top_items": top_items,
        "by_hour": by_hour,
        "by_hour_sales": by_hour_sales,
        "by_weekday": by_weekday,
        "item_ranking": item_ranking,
        "unsold_items": unsold,
    }
    if hotel_id is None:
        hotel_q = (
            select(Hotel.id, Hotel.name, Hotel.kind, *_totals_columns())
            .select_from(LedgerEntry)
            .join(Order, Order.id == LedgerEntry.order_id)
            .join(Hotel, Hotel.id == Order.hotel_id)
            .where(LedgerEntry.created_at >= r.start, LedgerEntry.created_at < r.end)
            .group_by(Hotel.id, Hotel.name, Hotel.kind)
        )
        rows = (await session.execute(hotel_q)).all()
        out["per_hotel"] = sorted(
            (
                {"hotel_id": str(row.id), "hotel": row.name, "kind": row.kind, **_row(row)}
                for row in rows
            ),
            key=lambda d: -d["net_received"],
        )
        # Hotels against liquor stores, so the two sides of the business can be compared.
        out["by_kind"] = {
            kind: {
                "stores": sum(1 for d in out["per_hotel"] if d["kind"] == kind),
                **{
                    k: sum(d[k] for d in out["per_hotel"] if d["kind"] == kind)
                    for k in (*TOTAL_KEYS, "received", "net_received")
                },
            }
            for kind in ("hotel", "liquor")
        }
    return out


async def payments(
    session: AsyncSession,
    r: Range,
    *,
    hotel_id: uuid.UUID | None,
    method: str | None,
    limit: int = 1000,
    offset: int = 0,
) -> list[dict]:
    """Money in (M-Pesa and cash) and refunds sent, newest first."""
    types = {"mpesa": ("till_received",), "cash": ("cash_received",), "refund": ("refund",)}
    wanted = types.get(method or "", (*RECEIVED, "refund"))
    stmt = (
        select(LedgerEntry, Order.code, Order.customer_name, Order.type, Hotel.name)
        .join(Order, Order.id == LedgerEntry.order_id)
        .join(Hotel, Hotel.id == Order.hotel_id)
        .where(
            LedgerEntry.created_at >= r.start,
            LedgerEntry.created_at < r.end,
            LedgerEntry.entry_type.in_(wanted),
        )
        .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if hotel_id is not None:
        stmt = stmt.where(Order.hotel_id == hotel_id)
    return [
        {
            "at": e.created_at,
            "kind": {"till_received": "mpesa", "cash_received": "cash"}.get(e.entry_type, "refund"),
            "amount": e.amount,
            "reference": e.reference,
            "order_code": code,
            "customer": name,
            "order_type": otype,
            "hotel": hotel,
        }
        for e, code, name, otype, hotel in (await session.execute(stmt)).all()
    ]
