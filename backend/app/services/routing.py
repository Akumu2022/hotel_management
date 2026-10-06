"""Road distance between the hotel and the customer's pin.

Uses an OSRM routing server (OpenStreetMap data). The public demo server is fine for a pilot
at ~100 orders/day; for production, self-host OSRM or switch the URL to a paid provider.
If routing fails or times out, falls back to straight-line distance x 1.3 (a typical town
road factor) so ordering never breaks. Results are cached by rounded coordinates.
"""

from collections import OrderedDict
from dataclasses import dataclass

import httpx

from app.core.config import get_config
from app.services.settings import distance_km as straight_km

ROAD_FACTOR = 1.3
TIMEOUT_S = 3.0
_CACHE_MAX = 2000
_cache: OrderedDict[tuple, float] = OrderedDict()


@dataclass(frozen=True)
class Distance:
    km: float  # what pricing uses, 1 decimal
    method: str  # road | estimated | straight


def _key(lat1, lng1, lat2, lng2) -> tuple:
    # ~11 m precision: taps a few metres apart share a cached route.
    return tuple(round(v, 4) for v in (lat1, lng1, lat2, lng2))


async def _osrm(lat1: float, lng1: float, lat2: float, lng2: float) -> float | None:
    url = f"{get_config().osrm_url}/{lng1},{lat1};{lng2},{lat2}"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            r = await client.get(url, params={"overview": "false"})
        data = r.json()
        if r.status_code == 200 and data.get("code") == "Ok" and data.get("routes"):
            return data["routes"][0]["distance"] / 1000
    except (httpx.HTTPError, ValueError):
        return None
    return None


async def distance(lat1: float, lng1: float, lat2: float, lng2: float, method: str) -> Distance:
    straight = straight_km(lat1, lng1, lat2, lng2)
    if method == "straight":
        return Distance(round(straight, 1), "straight")
    key = _key(lat1, lng1, lat2, lng2)
    if key in _cache:
        _cache.move_to_end(key)
        return Distance(round(_cache[key], 1), "road")
    road = await _osrm(lat1, lng1, lat2, lng2)
    if road is None:
        return Distance(round(straight * ROAD_FACTOR, 1), "estimated")
    _cache[key] = road
    if len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return Distance(round(road, 1), "road")


_route_cache: OrderedDict[tuple, tuple[float, list[list[float]] | None]] = OrderedDict()
ROUTE_TTL_S = 60.0
ROUTE_FAIL_TTL_S = 30.0  # after a failure, don't hammer the routing server
ROUTE_TIMEOUT_S = 15.0  # the line is drawn straight until it arrives, so waiting is fine


async def route_points(
    lat1: float, lng1: float, lat2: float, lng2: float
) -> list[list[float]] | None:
    """The road line from A to B as [lat, lng] points, for the customer's live map. None when
    routing is unavailable: the map then draws a straight line. Cached for a minute by a
    ~110 m grid, so a rider's pings never turn into a flood of routing requests."""
    import time

    key = tuple(round(v, 3) for v in (lat1, lng1, lat2, lng2))
    hit = _route_cache.get(key)
    if hit and time.monotonic() - hit[0] < (ROUTE_TTL_S if hit[1] else ROUTE_FAIL_TTL_S):
        return hit[1]
    url = f"{get_config().osrm_url}/{lng1},{lat1};{lng2},{lat2}"
    try:
        async with httpx.AsyncClient(timeout=ROUTE_TIMEOUT_S) as client:
            r = await client.get(url, params={"overview": "full", "geometries": "geojson"})
        data = r.json()
        if r.status_code == 200 and data.get("code") == "Ok" and data.get("routes"):
            pts = [[c[1], c[0]] for c in data["routes"][0]["geometry"]["coordinates"]]
            if len(pts) > 400:  # plenty for a map line
                step = len(pts) / 400
                pts = [pts[int(i * step)] for i in range(400)] + [pts[-1]]
            _route_cache[key] = (time.monotonic(), pts)
            if len(_route_cache) > 500:
                _route_cache.popitem(last=False)
            return pts
    except (httpx.HTTPError, ValueError, KeyError):
        pass
    _route_cache[key] = (time.monotonic(), None)
    return None
