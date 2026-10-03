"""Dashboard reports (DECISIONS D19): hotel admins see their hotel, the super admin all."""

import csv
import io
import uuid
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import Response

from app.api.deps import HotelAdmin, Session, SuperAdmin
from app.core.time import utcnow
from app.services import reports

hotel = APIRouter(prefix="/hotel/reports", tags=["reports"])
admin = APIRouter(prefix="/admin/reports", tags=["reports"])

Group = Literal["day", "week", "month"]
Method = Literal["mpesa", "cash", "refund"]


def _range(first: date | None, last: date | None) -> reports.Range:
    today = (utcnow() + reports.EAT).date()
    last = last or today
    return reports.Range.of(first or last - timedelta(days=6), last)


def _csv(rows: list[dict], name: str) -> Response:
    buf = io.StringIO()
    fields = ["at", "kind", "amount", "reference", "order_code", "customer", "order_type", "hotel"]
    writer = csv.DictWriter(buf, fieldnames=fields)
    writer.writeheader()
    for r in rows:
        writer.writerow({**r, "at": (r["at"] + reports.EAT).strftime("%Y-%m-%d %H:%M")})
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )


@hotel.get("")
async def hotel_summary(
    user: HotelAdmin,
    session: Session,
    start: date | None = None,
    end: date | None = None,
    group: Group = "day",
):
    return await reports.summary(session, _range(start, end), hotel_id=user.hotel_id, group=group)


@hotel.get("/payments")
async def hotel_payments(
    user: HotelAdmin,
    session: Session,
    start: date | None = None,
    end: date | None = None,
    method: Method | None = None,
    format: Literal["json", "csv"] = "json",
):
    r = _range(start, end)
    rows = await reports.payments(session, r, hotel_id=user.hotel_id, method=method)
    return _csv(rows, f"payments-{(r.start + reports.EAT).date()}") if format == "csv" else rows


@admin.get("")
async def admin_summary(
    _: SuperAdmin,
    session: Session,
    start: date | None = None,
    end: date | None = None,
    group: Group = "day",
    hotel_id: uuid.UUID | None = None,
):
    return await reports.summary(session, _range(start, end), hotel_id=hotel_id, group=group)


@admin.get("/payments")
async def admin_payments(
    _: SuperAdmin,
    session: Session,
    start: date | None = None,
    end: date | None = None,
    method: Method | None = None,
    hotel_id: uuid.UUID | None = None,
    format: Literal["json", "csv"] = "json",
):
    r = _range(start, end)
    rows = await reports.payments(session, r, hotel_id=hotel_id, method=method)
    return _csv(rows, f"payments-{(r.start + reports.EAT).date()}") if format == "csv" else rows
