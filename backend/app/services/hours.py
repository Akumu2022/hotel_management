"""Opening hours and "can this hotel take an order now" (DECISIONS D4).

Hours are local Africa/Nairobi times per weekday (0 = Monday). A closing time at or before the
opening time means the hotel closes after midnight. Orders stop `order_cutoff_minutes` before
closing.
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.models import Hotel, HotelHours

NAIROBI = ZoneInfo("Africa/Nairobi")


@dataclass(frozen=True)
class OpenStatus:
    is_open: bool  # can take an order right now
    state: str  # open | closing_soon | closed | paused | not_accepting
    closes_at: datetime | None  # end of the current opening window (UTC)
    opens_at: datetime | None  # start of the next window when closed (UTC)


def _windows(hours: list[HotelHours], local_now: datetime):
    """Opening windows (local datetimes) from yesterday through the next 7 days."""
    by_day = {h.weekday: h for h in hours}
    today = local_now.date()
    for offset in range(-1, 8):
        day = today + timedelta(days=offset)
        h = by_day.get(day.weekday())
        if h is None:
            continue
        start = datetime.combine(day, h.opens_at, NAIROBI)
        end_day = day if h.closes_at > h.opens_at else day + timedelta(days=1)
        end = datetime.combine(end_day, h.closes_at, NAIROBI)
        yield start, end


def open_status(
    hotel: Hotel, hours: list[HotelHours], now: datetime, cutoff_minutes: int
) -> OpenStatus:
    local_now = now.astimezone(NAIROBI)
    current = next(((s, e) for s, e in _windows(hours, local_now) if s <= local_now < e), None)
    upcoming = min((s for s, _ in _windows(hours, local_now) if s > local_now), default=None)
    utc = ZoneInfo("UTC")
    opens_at = upcoming.astimezone(utc) if upcoming else None

    if hotel.status == "paused":
        return OpenStatus(False, "paused", None, None)
    if current is None:
        return OpenStatus(False, "closed", None, opens_at)
    closes_at = current[1].astimezone(utc)
    if not hotel.accepting_orders:
        return OpenStatus(False, "not_accepting", closes_at, None)
    if local_now >= current[1] - timedelta(minutes=cutoff_minutes):
        return OpenStatus(False, "closed", closes_at, opens_at)
    if local_now >= current[1] - timedelta(minutes=cutoff_minutes + 30):
        return OpenStatus(True, "closing_soon", closes_at, None)
    return OpenStatus(True, "open", closes_at, None)


def category_available(available_from: time | None, available_to: time | None, now: datetime):
    """Time-based menus: a category with no window is always available."""
    if available_from is None or available_to is None:
        return True
    t = now.astimezone(NAIROBI).time()
    if available_from < available_to:
        return available_from <= t < available_to
    return t >= available_from or t < available_to  # window crosses midnight
