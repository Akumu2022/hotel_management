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

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_config() -> Config:
    return Config()
