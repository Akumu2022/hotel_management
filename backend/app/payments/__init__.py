"""Payments module: the only entry points the rest of the app may use.

    request_collection / confirm_delivery / reverse / request_withdrawal / get_balance

Pluggable: own `payments` schema, own flag (PAYMENTS_ENABLED, off by default), events out through
the outbox. Spec: Rider-Wallet-Daraja-Payment-Flow-v2, section 13.
"""

from app.payments.service import (
    confirm_delivery,
    get_balance,
    request_collection,
    request_withdrawal,
    reverse,
)

__all__ = [
    "confirm_delivery",
    "get_balance",
    "request_collection",
    "request_withdrawal",
    "reverse",
]
