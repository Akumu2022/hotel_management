"""Payments module settings. Everything is OFF by default: the pilot never notices this module."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class PaymentsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    payments_enabled: bool = False
    # Shadow mode: the ledger records what would have been credited, no money moves.
    payments_shadow: bool = True


@lru_cache
def get_payments_config() -> PaymentsConfig:
    return PaymentsConfig()
