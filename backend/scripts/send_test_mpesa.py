"""Development only: send a correct M-Pesa Till SMS for an order into the Android emulator, as if
the customer had just paid. The Chakula Till app on the emulator picks it up like a real one.

    python scripts/send_test_mpesa.py TREQEU
    python scripts/send_test_mpesa.py TREQEU --short 100            # paid 100 too little
    python scripts/send_test_mpesa.py TREQEU --name "PETER OTIENO"  # someone else paid

Amount, time and the customer's phone digits come from the order, so the message always fits.
"""

import argparse
import asyncio
import os
import secrets
import string
import subprocess
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Order

ADB = os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")


def message(code: str, amount: int, phone: str, name: str) -> str:
    t = datetime.now(UTC) + timedelta(hours=3)  # M-Pesa writes Kenya time
    hour = t.hour % 12 or 12
    ampm = "AM" if t.hour < 12 else "PM"
    masked = phone[:4] + "******" + phone[-3:]
    return (
        f"{code} Confirmed.on {t.day}/{t.month}/{t.year % 100} at {hour}:{t.minute:02d} {ampm}"
        f"KSH{amount:,}.00 received from {masked} {name}. New Account balance is KSH25,420.00. "
        "Transaction cost, KSH0.00."
    )


async def load(code: str) -> Order | None:
    async with SessionLocal() as session:
        return await session.scalar(select(Order).where(Order.code == code))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("order", help="order number, e.g. TREQEU")
    ap.add_argument("--name", help="payer name on the SMS (default: the checkout name)")
    ap.add_argument("--short", type=int, default=0, help="pay this much too little")
    ap.add_argument("--extra", type=int, default=0, help="pay this much too much")
    ap.add_argument("--code", help="M-Pesa code to use (default: a new random one)")
    args = ap.parse_args()

    order = asyncio.run(load(args.order.strip().lstrip("#").upper()))
    if order is None:
        raise SystemExit(f"No order {args.order}")
    alphabet = string.ascii_uppercase + string.digits
    code = (args.code or "UJ" + "".join(secrets.choice(alphabet) for _ in range(8))).upper()
    amount = order.till_amount - args.short + args.extra
    text = message(code, amount, order.customer_phone, (args.name or order.customer_name).upper())
    out = subprocess.run([ADB, "emu", "sms", "send", "MPESA", text], capture_output=True, text=True)
    if not out.stdout.strip().startswith("OK"):
        raise SystemExit(
            f"The emulator didn't take the SMS. Is it running? {out.stdout}{out.stderr}"
        )
    print(f"Sent: KES {amount:,} for #{order.code} ({order.status}), code {code}")


if __name__ == "__main__":
    main()
