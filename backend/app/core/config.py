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
    # Rider ID photos and selfies (D21): never served by the static file server.
    private_media_dir: str = "private_media"
    # M8 (D26): each Till phone's signing secret is HMAC(forwarder_key, its random salt), so the
    # database alone can't be used to forge payment messages. Set a long random value in prod.
    forwarder_key: str = "dev-forwarder-key-change-me-dev-forwarder-key"
    # "production" refuses to start with the development secrets above (see check_secrets).
    app_env: str = "development"
    # The login cookie is sent only over HTTPS when true. Must be true in production; false in
    # development so http://localhost and phones on the Wi-Fi can log in.
    cookie_secure: bool = False

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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_config() -> Config:
    return Config()
