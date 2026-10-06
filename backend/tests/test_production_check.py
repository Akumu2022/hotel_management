"""`python -m app.cli check-production`: what must be settled before going live."""

from app.core.config import Config

GOOD = {
    "app_env": "production",
    "jwt_secret": "j" * 48,
    "forwarder_key": "f" * 48,
    "cookie_secure": True,
    "database_url": "postgresql+asyncpg://hotel:S0me-long-pw@db:5432/hotel",
    "cors_origins": "https://order.example.co.ke",
    # Explicit, so the result never depends on the machine running the tests.
    "vapid_private_key": "",
    "redis_url": "",
    "osrm_url": "https://router.project-osrm.org/route/v1/driving",
    "payment_simulator": "",
}


def levels(cfg: Config) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for level, message in cfg.production_problems():
        out.setdefault(level, []).append(message)
    return out


def test_development_defaults_fail_every_launch_check():
    found = levels(Config(app_env="development", payment_simulator=""))
    assert len(found["fail"]) >= 7
    text = " ".join(found["fail"])
    assert "APP_ENV" in text and "JWT_SECRET" in text and "COOKIE_SECURE" in text
    assert "DATABASE_URL" in text and "CORS_ORIGINS" in text and "simulator" in text.lower()


def test_a_proper_production_setup_has_no_blockers_only_advice():
    found = levels(Config(**GOOD))
    assert "fail" not in found
    assert len(found["warn"]) == 3  # no Web Push keys, no Redis, public routing server


def test_each_optional_extra_clears_its_warning():
    cfg = Config(
        **{
            **GOOD,
            "vapid_private_key": "k" * 40,
            "redis_url": "redis://redis:6379/0",
            "osrm_url": "http://osrm:5000/route/v1/driving",
        }
    )
    assert "warn" not in levels(cfg)


def test_the_simulator_can_be_forced_on_but_is_then_a_blocker():
    cfg = Config(**{**GOOD, "payment_simulator": "true"})
    assert cfg.payment_simulator_enabled
    assert any("simulator" in m.lower() for m in levels(cfg)["fail"])
    assert not Config(**GOOD).payment_simulator_enabled
    assert Config(app_env="development", payment_simulator="").payment_simulator_enabled
    assert not Config(payment_simulator="false").payment_simulator_enabled
