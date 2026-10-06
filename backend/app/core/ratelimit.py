"""Sliding-window rate limits. In memory by default, which is right for one API process; set
REDIS_URL to share the counts between several processes (and to survive restarts). If Redis
can't be reached, requests are counted in memory rather than refused: a broken limiter must
never take the site down."""

import logging
import time
import uuid
from collections import defaultdict, deque

from fastapi import Request

from app.core.config import get_config
from app.core.errors import AppError

log = logging.getLogger("app.ratelimit")

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


# One atomic step: drop old hits, refuse if the window is full, else record this one.
_LUA = """
local k, now, win, lim = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', k, 0, now - win)
if redis.call('ZCARD', k) >= lim then
  local oldest = redis.call('ZRANGE', k, 0, 0, 'WITHSCORES')
  return {0, oldest[2]}
end
redis.call('ZADD', k, now, ARGV[4])
redis.call('EXPIRE', k, math.ceil(win) + 1)
return {1, '0'}
"""


class RedisRateLimiter:
    def __init__(self, url: str):
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        self._script = self._redis.register_script(_LUA)
        self._fallback = RateLimiter()

    async def hit(self, key: str, limit: int, window_s: int) -> None:
        now = time.time()
        try:
            ok, oldest = await self._script(
                keys=[f"rl:{key}"], args=[now, window_s, limit, f"{now}:{uuid.uuid4().hex[:8]}"]
            )
        except Exception:  # Redis down or slow: count here instead
            log.warning("rate limit store unavailable, counting in memory", exc_info=True)
            self._fallback.hit(key, limit, window_s)
            return
        if not int(ok):
            retry = int(float(oldest) + window_s - now) + 1
            raise AppError(429, "rate_limited", f"Too many attempts. Try again in {retry} s.")

    def reset(self) -> None:
        self._fallback.reset()


class Limiter:
    """What the routes use: Redis when configured, else memory. Chosen on first use."""

    def __init__(self):
        self._impl: RateLimiter | RedisRateLimiter | None = None

    def _get(self):
        if self._impl is None:
            url = get_config().redis_url
            self._impl = RedisRateLimiter(url) if url else RateLimiter()
        return self._impl

    async def hit(self, key: str, limit: int, window_s: int) -> None:
        impl = self._get()
        if isinstance(impl, RedisRateLimiter):
            await impl.hit(key, limit, window_s)
        else:
            impl.hit(key, limit, window_s)

    def reset(self) -> None:
        if self._impl is not None:
            self._impl.reset()


limiter = Limiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def limit(name: str, per_ip: int, window_s: int = 60):
    """FastAPI dependency: at most `per_ip` calls per `window_s` seconds per client IP."""

    async def dep(request: Request) -> None:
        await limiter.hit(f"{name}:ip:{client_ip(request)}", per_ip, window_s)

    return dep
