"""Latest payout-account balance reported by Daraja's Account Balance callback.
Kept in this process only: a miss just means 'unknown', and the float check fails closed."""

import time

TTL = 600  # seconds a reading stays usable
_last: tuple[int, float] | None = None


def fresh() -> int | None:
    return _last[0] if _last and time.monotonic() - _last[1] < TTL else None


def record(amount: int) -> None:
    global _last
    _last = (amount, time.monotonic())


def parse(body: dict) -> int | None:
    """'Utility Account|KES|700.00|700.00|0.00|0.00&Working Account|...' -> available KES of the
    Utility account (what B2C spends), falling back to the Working account."""
    res = body.get("Result", body)
    if int(res.get("ResultCode", -1)) != 0:
        return None
    for item in res.get("ResultParameters", {}).get("ResultParameter", []):
        if item.get("Key") != "AccountBalance":
            continue
        accounts = {}
        for part in str(item.get("Value", "")).split("&"):
            f = part.split("|")
            if len(f) >= 4:
                accounts[f[0].strip()] = f[3]
        for name in ("Utility Account", "Working Account"):
            if name in accounts:
                try:
                    return int(float(accounts[name]))
                except ValueError:
                    return None
    return None
