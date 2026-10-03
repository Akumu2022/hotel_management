import re

_DIGITS = re.compile(r"\D")


def normalize_phone(raw: str) -> str:
    """Normalize a Kenyan mobile number to 2547XXXXXXXX / 2541XXXXXXXX.

    Accepts 07xx/01xx, 7xx/1xx, 2547xx/2541xx and +2547xx forms. Raises ValueError otherwise.
    """
    digits = _DIGITS.sub("", raw or "")
    if digits.startswith("0") and len(digits) == 10:
        digits = "254" + digits[1:]
    elif len(digits) == 9 and digits[0] in "17":
        digits = "254" + digits
    if len(digits) == 12 and digits.startswith(("2547", "2541")):
        return digits
    raise ValueError("Enter a valid Kenyan mobile number, e.g. 0712 345 678")
