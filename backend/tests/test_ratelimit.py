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
