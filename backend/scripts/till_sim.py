"""Till phone simulator for your PC (no Android needed). Behaves like the Chakula Till app:
pairs with a code, then sends signed M-Pesa SMS to the server. Standard library only.

    # 1. Hotel admin: web app -> Settings -> Till phone -> "Pair a phone" shows an 8-letter code
    python scripts/till_sim.py pair ACDE-F347                      # server defaults to http://localhost:8000
    # 2. Customer places an order; take the tracking link's token (the part after /o/)
    python scripts/till_sim.py pay --track TOKEN --name "CUSTOMER NAME"  # name as typed at checkout
    # (a different payer name is sent to review on purpose; --name decides which you test)
    python scripts/till_sim.py pay --track TOKEN --short 100       # underpaid -> goes to review
    python scripts/till_sim.py pay --amount 670 --phone 254712000111 --name "MERCY NEKESA"
    python scripts/till_sim.py pay --track TOKEN --repeat          # same SMS twice: must count once
    python scripts/till_sim.py junk                                # non-M-Pesa text: ignored
    python scripts/till_sim.py heartbeat
    python scripts/till_sim.py status

The pairing is saved in scripts/.till_sim.json (delete it to start over).
"""

import argparse
import hashlib
import hmac
import json
import os
import secrets
import string
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".till_sim.json")


def load() -> dict:
    try:
        with open(STATE) as f:
            return json.load(f)
    except FileNotFoundError:
        sys.exit("Not paired yet. Run: python scripts/till_sim.py pair <CODE>")


def http(method: str, url: str, body: bytes | None = None, headers: dict | None = None):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            text = r.read().decode()
            return r.status, (json.loads(text) if text else {})
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        try:
            return e.code, json.loads(text)
        except ValueError:
            return e.code, {"raw": text}
    except urllib.error.URLError as e:
        sys.exit(f"Can't reach {url}: {e.reason}")


def signed(state: dict, path: str, payload: dict):
    body = json.dumps(payload).encode()
    ts, nonce = str(int(time.time())), secrets.token_hex(16)
    digest = hashlib.sha256(body).hexdigest()
    sig = hmac.new(
        bytes.fromhex(state["secret"]), f"{ts}\n{nonce}\n{digest}".encode(), hashlib.sha256
    ).hexdigest()
    return http(
        "POST",
        f"{state['server']}/api/v1/forwarder/{path}",
        body,
        {
            "Content-Type": "application/json",
            "X-Device-Id": state["device_id"],
            "X-Timestamp": ts,
            "X-Nonce": nonce,
            "X-Signature": sig,
        },
    )


def till_text(code: str, amount: int, phone: str, name: str) -> str:
    """A Till SMS in the real format (backend/tests/data)."""
    t = datetime.now(UTC) + timedelta(hours=3)  # M-Pesa writes Kenya time
    hour = t.hour % 12 or 12
    masked = phone[:4] + "******" + phone[-3:]
    return (
        f"{code} Confirmed.on {t.day}/{t.month}/{t.year % 100} at {hour}:{t.minute:02d} "
        f"{'AM' if t.hour < 12 else 'PM'}KSH{amount:,}.00 received from {masked} {name}. "
        "New Account balance is KSH25,420.00. Transaction cost, KSH0.00."
    )


def send(state: dict, sender: str, text: str, msg_id: str | None = None):
    msg = {
        "id": msg_id or secrets.token_hex(12),
        "sender": sender,
        "body": text,
        "received_at": int(time.time() * 1000),
    }
    status, res = signed(state, "sms", {"messages": [msg]})
    print(f"  server {status}: {res}")
    return msg["id"]


def cmd_pair(a):
    server = a.server.rstrip("/")
    body = json.dumps({"code": a.code, "label": a.label, "app_version": "sim"}).encode()
    status, res = http(
        "POST", f"{server}/api/v1/forwarder/pair", body, {"Content-Type": "application/json"}
    )
    if status != 200:
        sys.exit(f"Pairing failed ({status}): {res}")
    with open(STATE, "w") as f:
        json.dump({**res, "server": server}, f)
    print(f"Paired with {res['hotel_name']} (Till {res['till_number']}). Ready to send SMS.")


def cmd_pay(a):
    state = load()
    amount = a.amount
    if a.track:
        status, order = http("GET", f"{state['server']}/api/v1/track/{a.track}")
        if status != 200:
            sys.exit(f"Order not found ({status}): {order}")
        amount = order["till_amount"]
        print(f"Order {order['code']} ({order['status']}): Till amount KSH {amount}")
    if not amount:
        sys.exit("Give --track TOKEN or --amount N")
    amount -= a.short
    code = a.code or "S" + "".join(
        secrets.choice(string.ascii_uppercase + string.digits) for _ in range(9)
    )
    text = till_text(code, amount, a.phone, a.name)
    print(f"SMS: {text}")
    mid = send(state, "MPESA", text)
    if a.repeat:
        print("Sending the same SMS again (must be harmless):")
        send(state, "MPESA", text, mid)
    if a.track:
        status, order = http("GET", f"{state['server']}/api/v1/track/{a.track}")
        print(f"Order is now: {order.get('status')}")


def cmd_junk(_):
    send(load(), "SAFARICOM", "Dial *144# to enjoy bonus data this weekend!")


def cmd_heartbeat(_):
    state = load()
    status, res = signed(
        state,
        "heartbeat",
        {
            "app_version": "sim",
            "battery": 90,
            "charging": True,
            "pending": 0,
            "sms_permission": True,
        },
    )
    print(status, res)


def cmd_status(_):
    s = load()
    print(
        f"Paired device {s['device_id']} -> {s['hotel_name']} "
        f"(Till {s['till_number']}) at {s['server']}"
    )


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--server", default=os.environ.get("TILL_SIM_SERVER", "http://localhost:8000"))
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("pair")
    s.add_argument("code")
    s.add_argument("--label", default="PC simulator")
    s.set_defaults(fn=cmd_pair)
    s = sub.add_parser("pay")
    s.add_argument("--track", help="customer's tracking token (the part after /o/)")
    s.add_argument("--amount", type=int)
    s.add_argument("--short", type=int, default=0, help="pay this much too little")
    s.add_argument("--phone", default="254712000111")
    s.add_argument("--name", default="MERCY NEKESA")
    s.add_argument("--code", help="M-Pesa code (default: random)")
    s.add_argument("--repeat", action="store_true", help="send the same SMS twice")
    s.set_defaults(fn=cmd_pay)
    sub.add_parser("junk").set_defaults(fn=cmd_junk)
    sub.add_parser("heartbeat").set_defaults(fn=cmd_heartbeat)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
