"""Every real sample is a test (spec section 7), plus the spacing/format variants a phone may
show, reversals and unreadable text."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.services.sms_parser import parse

SAMPLES = Path(__file__).resolve().parents[2] / "docs" / "sms_samples" / "till_payments.txt"


def blocks() -> list[str]:
    text = SAMPLES.read_text(encoding="utf8")
    return [b.strip() for b in text.split("\n\n") if b.strip() and not b.lstrip().startswith("#")]


def test_every_real_sample_parses():
    found = blocks()
    assert len(found) >= 2
    for raw in found:
        p = parse(raw)
        assert p.status == "parsed", (raw, p.reason)
        assert len(p.code) == 10 and p.amount > 0 and p.phone_digits.startswith("2547")


def test_real_sample_fields():
    p = parse(blocks()[0])
    assert (p.code, p.amount, p.phone_digits, p.sender_name) == (
        "UJ2H08M4M3",
        40,
        "254700000001",
        "Jane Doe",
    )
    assert p.paid_at == datetime(2026, 10, 2, 16, 37, tzinfo=UTC)  # 7:37 PM EAT


@pytest.mark.parametrize(
    "raw",
    [
        # spaces the phone app hides, and line breaks
        "UJ2H08M4M3 Confirmed. on 2/10/26 at 7:37 PM KSH40.00 received from 254700000001 Jane Doe. New Account balance is KSH1,090.05.",
        "UJ2H08M4M3 Confirmed.\non 2/10/26 at 7:37 PM\nKsh40.00 received from\n254700000001 Jane Doe.\nNew Account balance is KSH1,090.05.",
        "uj2h08m4m3 confirmed.on 2/10/26 at 7:37 pmksh40.00 received from 254700000001 Jane Doe. new account balance is ksh1,090.05.",
    ],
)
def test_spacing_and_case_variants(raw):
    p = parse(raw)
    assert (p.status, p.code, p.amount) == ("parsed", "UJ2H08M4M3", 40)


def test_thousands_and_masked_phone_and_morning_time():
    p = parse(
        "UJ2X00000A Confirmed.on 1/10/26 at 12:05 AMKSH1,050.00 received from 2547******635 Test Person. New Account balance is KSH2,000.00."
    )
    assert (p.status, p.amount, p.phone_digits) == ("parsed", 1050, "2547******635")
    assert p.paid_at == datetime(2026, 9, 30, 21, 5, tzinfo=UTC)  # 00:05 EAT


@pytest.mark.parametrize(
    ("amount", "expected"),
    [("1420.00", 1420), ("1,420.00", 1420), ("12500", 12500), ("12,500.00", 12500), ("720", 720)],
)
def test_amount_with_or_without_thousands_comma(amount, expected):
    p = parse(
        f"UJ3TEST001 Confirmed.on 3/10/26 at 10:51 AMKSH{amount} received from 2547******999 "
        "KAMAU DANIEL JAMES. New Account balance is KSH5,420.00. Transaction cost, KSH0.00."
    )
    assert (p.status, p.amount, p.sender_name) == ("parsed", expected, "KAMAU DANIEL JAMES")


def test_misplaced_comma_is_not_guessed():
    p = parse(
        "UJ3TEST001 Confirmed.on 3/10/26 at 10:51 AMKSH14,20.00 received from 2547******999 "
        "KAMAU DANIEL JAMES. New Account balance is KSH5,420.00."
    )
    assert p.status == "failed"


@pytest.mark.parametrize(
    "raw",
    [
        "UJ2H08M4M3 Confirmed.on 2/10/26 at 7:37 PMKSH40.50 received from 254700000001 Jane Doe. New Account balance is KSH1,090.05.",  # cents
        "UJ2H08M4M3 Confirmed.on 31/2/26 at 7:37 PMKSH40.00 received from 254700000001 Jane Doe. New Account balance is KSH1.",  # bad date
        "Your M-PESA balance is KSH1,090.05.",
        "Hello, win a prize today!",
    ],
)
def test_unclear_messages_fail_instead_of_guessing(raw):
    assert parse(raw).status == "failed"


def test_reversal_needs_a_code():
    assert (
        parse("Transaction UJ2H08M4M3 has been reversed. Your account balance is ...").status
        == "reversal"
    )
    assert parse("Transaction UJ2H08M4M3 has been reversed.").code == "UJ2H08M4M3"
    assert parse("A transaction was reversed.").status == "failed"


async def test_admin_paste_sms_end_to_end(client, db):
    from tests.factories import auth_header, make_hotel, make_order, make_user

    hotel = await make_hotel(db)
    order = await make_order(db, hotel)  # Till 770
    admin = auth_header(await make_user(db, "super_admin"))
    await client.post(
        f"/api/v1/track/{order.tracking_token}/payment-code", json={"code": "UJ2H08M4M3"}
    )
    raw = (
        "UJ2H08M4M3 Confirmed.on 2/10/26 at 7:37 PMKSH770.00 received from 254700000001 Jane Doe. "
        "New Account balance is KSH1,090.05. Transaction cost, KSH0.00."
    )
    # paid_at in the SMS is a fixed date; the order was created "now", so allow it via an old order
    order.created_at = datetime(2026, 10, 2, 16, 0, tzinfo=UTC)
    await db.flush()
    r = (
        await client.post(
            "/api/v1/admin/test-sms",
            headers=admin,
            json={"till_number": hotel.till_number, "raw_text": raw},
        )
    ).json()
    assert (r["parse_status"], r["amount"], r["result"]) == ("parsed", 770, "paid")
    bad = (
        await client.post(
            "/api/v1/admin/test-sms",
            headers=admin,
            json={"till_number": hotel.till_number, "raw_text": "random words here"},
        )
    ).json()
    assert bad["result"] == "parse_failed"
