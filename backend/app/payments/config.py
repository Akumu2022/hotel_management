"""Payments module settings. Everything is OFF by default: the pilot never notices this module."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class PaymentsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    payments_enabled: bool = False
    # Shadow mode: the ledger records what would have been credited, no money moves.
    payments_shadow: bool = True
    # "fake" (tests, shadow) or "daraja". Keys live only in .env on the server.
    payments_provider: str = "fake"
    daraja_env: str = "sandbox"  # sandbox | production
    daraja_consumer_key: str = ""
    daraja_consumer_secret: str = ""
    daraja_shortcode: str = "174379"
    daraja_passkey: str = ""
    # Public https base (tunnel in sandbox) and the long secret in the callback path.
    daraja_callback_base: str = ""
    daraja_callback_token: str = ""
    # Safaricom source IPs, comma separated. Empty = not enforced (sandbox).
    daraja_allowed_ips: str = ""


@lru_cache
def get_payments_config() -> PaymentsConfig:
    return PaymentsConfig()
