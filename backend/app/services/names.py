"""Does the name on the M-Pesa message belong to the person who ordered? (owner, D25)

The name typed at checkout is compared with the payer's name on the Till SMS, word by word, in
any order: "James Kamau" matches "KAMAU DANIEL JAMES" (2 names) and "James Onyango" (1 name).
Small spelling differences count (Mohamed / Mohammed, Wanjiku / Wanjku), and so does a short
form ("Kam" for Kamau). One or two letters ("J.", "Mo") never count on their own.

    2 = two or more names match (strong), 1 = one name matches, 0 = none.

It never blocks a payment on its own (people pay for each other); it decides whether an SMS
without a code can be matched automatically, and it is shown to the cashier.
"""

import re
import unicodedata

STRONG, PARTIAL, NONE = 2, 1, 0


def words(name: str | None) -> list[str]:
    """Lower-case name words of 3+ letters, accents removed."""
    if not name:
        return []
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return [w for w in re.split(r"[^a-z]+", plain.lower()) if len(w) >= 3]


def _edits(a: str, b: str, limit: int) -> int:
    """Levenshtein distance, stopping early once it exceeds `limit`."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def same_word(a: str, b: str) -> bool:
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 3 and long_.startswith(short):
        return True  # "Kam" / "Kamau", "Abdi" / "Abdirahman"
    if len(short) >= 5:
        return _edits(a, b, 1) <= 1  # one slip: "Wanjku" / "Wanjiku"
    return False


def match(checkout_name: str | None, payer_name: str | None) -> int | None:
    """How many checkout names appear in the payer's name (capped at 2); None if unknown."""
    wanted, have = words(checkout_name), words(payer_name)
    if not wanted or not have:
        return None
    left = list(have)
    found = 0
    for w in wanted:
        hit = next((h for h in left if same_word(w, h)), None)
        if hit is not None:
            left.remove(hit)  # each payer name counts once
            found += 1
    return min(found, STRONG)


LABEL = {STRONG: "Name matches", PARTIAL: "One name matches", NONE: "Different name"}
