"""In-memory sliding-window rate limits. Correct for the single API process the spec runs at
launch (section 4); moving to several processes needs a shared store."""

import time
from collections import defaultdict, deque

from fastapi import Request

from app.core.errors import AppError

# Keys idle this long are dropped, so memory doesn't grow with every visitor ever seen. Longer
# than any window in use (the longest is a few minutes).
IDLE_S = 3600
SWEEP_EVERY = 1000  # hits between sweeps


class RateLimiter:
    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._calls = 0

    def _sweep(self, now: float) -> None:
        idle = [k for k, q in self._hits.items() if not q or q[-1] <= now - IDLE_S]
        for k in idle:
            del self._hits[k]

    def hit(self, key: str, limit: int, window_s: int) -> None:
        now = time.monotonic()
        self._calls += 1
        if self._calls % SWEEP_EVERY == 0:
            self._sweep(now)
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
