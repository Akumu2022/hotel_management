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


@dataclass
class DisburseAccepted:
    conversation_id: str
    final: "DisburseStatus | None" = None  # only the fake/shadow provider knows the result at once


@dataclass
class DisburseStatus:
    """None result_code = Daraja has not finished (or cannot say yet)."""

    result_code: int | None
    reason: str = ""
    transaction_id: str | None = None


class Provider(Protocol):
    async def collect(
        self, *, phone: str, amount: int, account_ref: str, callback_url: str
    ) -> CollectAccepted: ...

    async def query_collection(self, checkout_request_id: str) -> CollectStatus: ...

    async def disburse(
        self, *, phone: str, amount: int, originator_id: str, result_url: str, timeout_url: str
    ) -> DisburseAccepted:
        """B2C. Raises ProviderError ONLY for a clear rejection. Any other exception (network,
        timeout, 5xx) means "we do not know if it was sent"."""
        ...

    async def pay_till(
        self, *, till: str, amount: int, originator_id: str, result_url: str, timeout_url: str
    ) -> DisburseAccepted:
        """B2B to a hotel's Till. Same ProviderError / unknown-outcome rules as disburse."""
        ...

    async def query_disbursement(
        self, originator_id: str, *, result_url: str, timeout_url: str
    ) -> DisburseStatus | None:
        """Ask what became of a payout. Daraja answers on the result URL (returns None here);
        the fake returns an answer directly."""
        ...

    async def account_balance(self) -> int:
        """Spendable KES in the payout account."""
        ...
