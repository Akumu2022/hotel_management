"""M-Pesa Till SMS parser (spec section 7). Built from real Till messages (docs/sms_samples).

Real sample format (names/numbers anonymised in the samples file):

    UJ2H08M4M3 Confirmed.on 2/10/26 at 7:37 PMKSH40.00 received from 254700000001 Jane Doe.
    New Account balance is KSH1,090.05. Transaction cost, KSH0.00. ...

Rules:
- Spaces between parts are optional (phone apps hide some), letter case is ignored.
- The amount must be a positive whole shilling; any cents mean "flag for review".
- Date is day/month/year in Kenyan time (EAT, UTC+3), converted to UTC.
- Anything that does not match cleanly is FAILED and goes to a human. We never guess.
- Messages that mention a reversal are REVERSAL only if they contain a transaction code; the
  matching code decides which payment is flagged.
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone

EAT = timezone(timedelta(hours=3))

_PAYMENT = re.compile(
    r"""^\s*
    (?P<code>[A-Z0-9]{10})\s*Confirmed\.?\s*
    on\s*(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s*
    at\s*(?P<time>\d{1,2}:\d{2})\s*(?P<ampm>[AP]M)\s*
    Ksh\s*(?P<amount>\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)\s*
    received\s*from\s*
    (?P<phone>\+?[\d*]{9,13})\s*
    (?P<name>[^.]+?)\.\s*
    New\s*Account\s*balance
    """,
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)
_REVERSAL_WORD = re.compile(r"revers", re.IGNORECASE)
_ANY_CODE = re.compile(r"\b([A-Z0-9]{10})\b")


@dataclass(frozen=True)
class Parsed:
    status: str  # parsed | failed | reversal | ignored
    code: str | None = None
    amount: int | None = None
    paid_at: datetime | None = None
    phone_digits: str | None = None
    sender_name: str | None = None
    reason: str | None = None  # why it failed


def _amount(raw: str) -> int | None:
    value = raw.replace(",", "")
    whole, _, cents = value.partition(".")
    if cents and int(cents) != 0:
        return None  # M-Pesa Till payments are whole shillings; cents need a human
    n = int(whole)
    return n if n > 0 else None


def _when(date: str, time: str, ampm: str) -> datetime | None:
    d, m, y = (int(x) for x in date.split("/"))
    if y < 100:
        y += 2000
    hh, mm = (int(x) for x in time.split(":"))
    if not (1 <= hh <= 12 and 0 <= mm <= 59):
        return None
    hh = hh % 12 + (12 if ampm.upper() == "PM" else 0)
    try:
        return datetime(y, m, d, hh, mm, tzinfo=EAT).astimezone(UTC)
    except ValueError:
        return None


def parse(raw: str) -> Parsed:
    text = " ".join((raw or "").split())  # newlines and double spaces -> single spaces
    if not text:
        return Parsed("ignored", reason="empty")

    if _REVERSAL_WORD.search(text):
        codes = _ANY_CODE.findall(text.upper())
        if codes:
            return Parsed("reversal", code=codes[0])
        return Parsed("failed", reason="reversal without a transaction code")

    m = _PAYMENT.match(text)
    if not m:
        return Parsed("failed", reason="not a recognised Till payment message")
    amount = _amount(m["amount"])
    if amount is None:
        return Parsed(
            "failed", code=m["code"].upper(), reason=f"amount {m['amount']} is not whole shillings"
        )
    paid_at = _when(m["date"], m["time"], m["ampm"])
    if paid_at is None:
        return Parsed("failed", code=m["code"].upper(), reason="unreadable date or time")
    return Parsed(
        "parsed",
        code=m["code"].upper(),
        amount=amount,
        paid_at=paid_at,
        phone_digits=m["phone"].lstrip("+"),
        sender_name=" ".join(m["name"].split()),
    )
