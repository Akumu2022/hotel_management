"""In-memory provider for tests and shadow mode: no network, no money."""

import itertools

from app.payments.adapter import CollectAccepted, CollectStatus, ProviderError


class FakeProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_next: str | None = None
        self.statuses: dict[str, CollectStatus] = {}
        self._n = itertools.count(1)

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
