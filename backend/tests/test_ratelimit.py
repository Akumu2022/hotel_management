"""The in-memory rate limiter forgets idle visitors (memory stays flat)."""

from app.core import ratelimit


def test_idle_keys_are_dropped(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: clock[0])
    lim = ratelimit.RateLimiter()
    for i in range(500):
        lim.hit(f"quote:ip:10.0.{i // 256}.{i % 256}", 60, 60)
    assert len(lim._hits) == 500
    clock[0] += ratelimit.IDLE_S + 1
    for _ in range(ratelimit.SWEEP_EVERY):
        lim.hit("quote:ip:10.9.9.9", 10**6, 60)
    assert list(lim._hits) == ["quote:ip:10.9.9.9"]


async def test_redis_limiter_falls_back_to_memory_when_redis_is_down():
    lim = ratelimit.RedisRateLimiter("redis://127.0.0.1:1/0")  # nothing listens here
    for _ in range(3):
        await lim.hit("login:ip:9.9.9.9", 3, 60)
    try:
        await lim.hit("login:ip:9.9.9.9", 3, 60)
        raise AssertionError("the fourth hit should have been refused")
    except ratelimit.AppError as e:
        assert e.status_code == 429


async def test_redis_limiter_shares_counts_between_processes():
    """Needs a real Redis: TEST_REDIS_URL=redis://host:6379/15 pytest tests/test_ratelimit.py"""
    import os
    import uuid

    import pytest

    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL not set")
    key = f"test:{uuid.uuid4().hex}"
    first, second = (
        ratelimit.RedisRateLimiter(url),
        ratelimit.RedisRateLimiter(url),
    )  # 2 "processes"
    await first.hit(key, 2, 60)
    await second.hit(key, 2, 60)
    with pytest.raises(ratelimit.AppError) as e:
        await first.hit(key, 2, 60)
    assert e.value.status_code == 429
