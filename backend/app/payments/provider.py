from functools import lru_cache

from app.payments.config import get_payments_config


@lru_cache
def get_provider():
    cfg = get_payments_config()
    if cfg.payments_provider == "daraja":
        from app.payments.daraja import DarajaProvider

        return DarajaProvider(cfg)
    from app.payments.fake import FakeProvider

    return FakeProvider()
