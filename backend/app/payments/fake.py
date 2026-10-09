"""In-memory provider for tests and shadow mode: no network, no money."""

import itertools

from app.payments.adapter import (
    CollectAccepted,
    CollectStatus,
    DisburseAccepted,
    DisburseStatus,
    ProviderError,
)


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_next: str | None = None
        self.statuses: dict[str, CollectStatus] = {}
        self._n = itertools.count(1)
        self.disbursed: list[dict] = []
        self.disburse_error: Exception | None = None  # raised on the next disburse()
        self.disburse_statuses: dict[str, DisburseStatus] = {}
        self.balance = 10_000_000
        self.auto_complete = False  # shadow mode: payouts finish at once, no money moves

    async def collect(self, *, phone, amount, account_ref, callback_url) -> CollectAccepted:
        self.calls.append(
            {"phone": phone, "amount": amount, "account_ref": account_ref, "url": callback_url}
        )
        if self.fail_next:
            msg, self.fail_next = self.fail_next, None
            raise ProviderError(msg)
        n = next(self._n)
        return CollectAccepted(f"ws_CO_fake_{n}", f"fake-merchant-{n}")

    async def query_collection(self, checkout_request_id: str) -> CollectStatus:
        return self.statuses.get(checkout_request_id, CollectStatus(result_code=None))

    async def disburse(self, *, phone, amount, originator_id, result_url, timeout_url):
        self.disbursed.append({"phone": phone, "amount": amount, "originator_id": originator_id})
        if self.disburse_error:
            err, self.disburse_error = self.disburse_error, None
            raise err
        final = (
            DisburseStatus(0, "shadow", f"SHADOW{originator_id[:8].upper()}")
            if self.auto_complete
            else None
        )
        return DisburseAccepted(f"AG_fake_{originator_id[:8]}", final)

    async def pay_till(self, *, till, amount, originator_id, result_url, timeout_url):
        self.disbursed.append({"till": till, "amount": amount, "originator_id": originator_id})
        if self.disburse_error:
            err, self.disburse_error = self.disburse_error, None
            raise err
        final = (
            DisburseStatus(0, "shadow", f"SHADOW{originator_id[:8].upper()}")
            if self.auto_complete
            else None
        )
        return DisburseAccepted(f"AG_fake_{originator_id[:8]}", final)

    async def query_disbursement(self, originator_id, *, result_url, timeout_url):
        return self.disburse_statuses.get(originator_id)

    async def account_balance(self) -> int:
        return self.balance
