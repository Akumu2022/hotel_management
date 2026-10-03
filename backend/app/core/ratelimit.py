"""In-memory sliding-window rate limits. Correct for the single API process the spec runs at
launch (section 4); moving to several processes needs a shared store."""

import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.errors import AppError


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def hit(self, key: str, limit: int, window_s: int) -> None:
        now = time.monotonic()
        q = self._hits[key]
        while q and q[0] <= now - window_s:
            q.popleft()
        if len(q) >= limit:
            retry = int(q[0] + window_s - now) + 1
            raise AppError(429, "rate_limited", f"Too many attempts. Try again in {retry} s.")
        q.append(now)

    def reset(self) -> None:
        self._hits.clear()


limiter = RateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit(name: str, per_ip: int, window_s: int = 60):
    """FastAPI dependency: at most `per_ip` calls per `window_s` seconds per client IP."""

    async def dep(request: Request) -> None:
        limiter.hit(f"{name}:ip:{client_ip(request)}", per_ip, window_s)

    return dep
