"""Provider interface. Daraja sits behind it, so moving to a licensed aggregator is one swap."""

from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    """The provider clearly rejected the request (safe to treat as failed, not unknown)."""


@dataclass
class CollectAccepted:
    checkout_request_id: str
    merchant_request_id: str


@dataclass
class CollectStatus:
    result_code: int | None  # None = still pending
    result_desc: str = ""
    receipt: str | None = None


class Provider(Protocol):
    async def collect(
        self, *, phone: str, amount: int, account_ref: str, callback_url: str
    ) -> CollectAccepted: ...

    async def query_collection(self, checkout_request_id: str) -> CollectStatus: ...
