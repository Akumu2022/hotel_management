from functools import lru_cache

from app.payments.config import get_payments_config


@lru_cache
def get_provider():
    cfg = get_payments_config()
    # Shadow mode can never move real money, whatever else is configured.
    if cfg.payments_provider == "daraja" and not cfg.payments_shadow:
        from app.payments.daraja import DarajaB2C

        return DarajaB2C(cfg)
    from app.payments.fake import FakeProvider

    fake = FakeProvider()
    fake.auto_complete = True  # shadow: payouts "succeed" at once in the ledger only
    return fake
