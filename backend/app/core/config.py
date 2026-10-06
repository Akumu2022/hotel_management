from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://hotel:hotel@localhost:5432/hotel"
    test_database_url: str = "postgresql+asyncpg://hotel:hotel@localhost:5432/hotel_test"
    jwt_secret: str = "dev-secret-change-me-dev-secret-change-me"
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    cors_origins: str = "http://localhost:5173"
    media_dir: str = "media"
    media_url: str = "/media"
    # Rider ID photos and selfies: never served by the static file server.
    private_media_dir: str = "private_media"
    # Each Till phone's signing secret is HMAC(forwarder_key, its random salt), so the
    # database alone can't be used to forge payment messages. Set a long random value in prod.
    forwarder_key: str = "dev-forwarder-key-change-me-dev-forwarder-key"
    # "production" refuses to start with the development secrets above (see check_secrets).
    app_env: str = "development"
    # The login cookie is sent only over HTTPS when true. Must be true in production; false in
    # development so http://localhost and phones on the Wi-Fi can log in.
    cookie_secure: bool = False
    # The admin tool that fabricates a payment (any code, any amount) is development-only. Set
    # true to allow it on a production server (not recommended); empty = on unless production.
    payment_simulator: str = ""
    # Road routing for distances and the customer's live map. The free public server is for the
    # pilot only (slow, no guarantees); point this at your own OSRM server in production.
    # Shared store for rate limits when the API runs as several processes (redis://host:6379/0).
    # Empty = in-memory limits, correct for a single process.
    redis_url: str = ""
    # Web Push (alarms when the browser is closed). Generate with `python -m app.cli vapid-keys`;
    # empty = push is off and the page rings only while it is open.
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"
    osrm_url: str = "https://router.project-osrm.org/route/v1/driving"

    def check_secrets(self) -> None:
        """Stop a production server that would sign logins or Till messages with a known key."""
        if self.app_env != "production":
            return
        weak = [
            name
            for name, value in (
                ("JWT_SECRET", self.jwt_secret),
                ("FORWARDER_KEY", self.forwarder_key),
            )
            if "change-me" in value or len(value) < 32
        ]
        if weak:
            raise RuntimeError(
                f"Set strong secrets before running in production: {', '.join(weak)}"
            )
        if not self.cookie_secure:
            raise RuntimeError("Set COOKIE_SECURE=true in production (HTTPS only login cookie)")

    def production_problems(self) -> list[tuple[str, str]]:
        """Everything to settle before real customers use this server: ("fail", ...) blocks
        going live, ("warn", ...) is worth fixing soon, ("ok", ...) is fine."""
        out: list[tuple[str, str]] = []

        def check(ok: bool, level: str, good: str, bad: str) -> None:
            out.append(("ok", good) if ok else (level, bad))

        check(self.app_env == "production", "fail", "APP_ENV=production", "Set APP_ENV=production")
        for name, value in (("JWT_SECRET", self.jwt_secret), ("FORWARDER_KEY", self.forwarder_key)):
            strong = "change-me" not in value and len(value) >= 32
            check(
                strong, "fail", f"{name} is a strong secret", f"{name} is weak or still the default"
            )
        check(self.cookie_secure, "fail", "Login cookie is HTTPS-only", "Set COOKIE_SECURE=true")
        check(
            ":hotel@" not in self.database_url,
            "fail",
            "Database password is not the default",
            "DATABASE_URL still uses the default hotel/hotel login",
        )
        check(
            not any("localhost" in o or "127.0.0.1" in o for o in self.cors_origin_list),
            "fail",
            "CORS_ORIGINS lists only your real site",
            "CORS_ORIGINS still allows localhost",
        )
        check(
            not self.payment_simulator_enabled,
            "fail",
            "Payment simulator is off",
            "Payment simulator is on: it can mark orders paid with no money",
        )
        check(
            bool(self.vapid_private_key),
            "warn",
            "Web Push is set up",
            "No VAPID keys: alarms won't reach closed browsers",
        )
        check(
            bool(self.redis_url),
            "warn",
            "Shared rate limits (Redis)",
            "No REDIS_URL: rate limits are per process (fine for one process)",
        )
        check(
            "router.project-osrm.org" not in self.osrm_url,
            "warn",
            "Own road-routing server",
            "Using the free public routing server: slow, no guarantees",
        )
        return out

    @property
    def payment_simulator_enabled(self) -> bool:
        flag = self.payment_simulator.strip().lower()
        if flag:
            return flag in ("1", "true", "yes", "on")
        return self.app_env != "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_config() -> Config:
    return Config()
