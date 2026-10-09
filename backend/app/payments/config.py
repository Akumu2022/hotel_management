"""Payments module settings. Everything is OFF by default: the pilot never notices this module."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class PaymentsConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    payments_enabled: bool = False
    # Shadow mode: the ledger records what would have been credited, no money moves.
    payments_shadow: bool = True
    # Customers pay by STK Push at checkout. Needs PAYMENTS_ENABLED, shadow OFF, and the hotel
    # switched on in the admin list. Until refunds to customers are automated, sandbox only.
    payments_stk_checkout: bool = False
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
    # B2C (payouts) uses its own Daraja app and initiator. Never logged, never in the repo.
    daraja_b2c_consumer_key: str = ""
    daraja_b2c_consumer_secret: str = ""
    daraja_b2c_shortcode: str = ""
    daraja_initiator_name: str = ""
    daraja_security_credential: str = ""
    # Payout rules (spec 1.3). Amounts in KES.
    payout_min: int = 50
    payout_rider_daily_cap: int = 10000
    payout_global_daily_cap: int = 200000
    settle_hotels_to_till: bool = False  # False = B2C to the hotel phone; True = B2B to its Till
    settle_hotel_daily_cap: int = 100000
    payout_extra_charge: int = 30  # taken from the rider on a 2nd+ withdrawal in a day


@lru_cache
def get_payments_config() -> PaymentsConfig:
    return PaymentsConfig()
