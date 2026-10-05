"""D1: admin-entered settings, validated, audit-logged, with per-hotel overrides."""

import pytest
from sqlalchemy import select

from app.models import AuditLog, Setting
from app.services import settings
from tests.factories import auth_header, make_hotel, make_user

URL = "/api/v1/admin/settings"


@pytest.fixture
async def admin(db):
    return await make_user(db, "super_admin")


async def test_migration_seed_matches_defaults(db):
    rows = (await db.execute(select(Setting))).scalars().all()
    assert {r.key: r.value for r in rows} == {r["key"]: r["value"] for r in settings.seed_rows()}


async def test_seeded_values_are_flagged_unconfirmed(client, admin):
    body = (await client.get(URL, headers=auth_header(admin))).json()
    assert body["unconfirmed"] is True
    assert body["commission_percent"] == 10
    assert body["service_fee"] == 20
    assert [b["fee"] for b in body["rider_fee_bands"]] == [100, 150, 200]
    assert body["unpaid_expiry_minutes"] == 20


async def test_update_converts_percent_audits_and_clears_banner(client, db, admin):
    r = await client.put(
        URL, headers=auth_header(admin), json={"commission_percent": 12.5, "service_fee": 25}
    )
    assert r.status_code == 200, r.text
    assert r.json()["commission_percent"] == 12.5
    assert r.json()["unconfirmed"] is False

    stored = await db.get(Setting, "commission_bp")
    assert stored.value == 1250
    logs = (
        (await db.execute(select(AuditLog).where(AuditLog.action == "settings.update")))
        .scalars()
        .all()
    )
    assert {(log.target_id, log.details["old"], log.details["new"]) for log in logs} == {
        ("commission_bp", 1000, 1250),
        ("service_fee", 20, 25),
    }
    assert all(log.actor_id == admin.id for log in logs)
    assert (await client.get(URL, headers=auth_header(admin))).json()["unconfirmed"] is False


async def test_saving_unchanged_values_confirms_without_audit_noise(client, db, admin):
    r = await client.put(URL, headers=auth_header(admin), json={})
    assert r.json()["unconfirmed"] is False
    logs = (await db.execute(select(AuditLog))).scalars().all()
    assert logs == []


@pytest.mark.parametrize(
    "payload",
    [
        {"commission_percent": 50.01},
        {"commission_percent": -1},
        {"commission_percent": 10.125},  # more than two decimals
        {"service_fee": 20.5},  # money is whole shillings
        {"service_fee": -1},
        {"rider_fee": "100"},
        {"unpaid_expiry_minutes": 0},
        {"rider_payout_default": "monthly"},
        {"acceptance_alert_minutes": 10, "acceptance_timeout_minutes": 10},
        {"delivery_zone": [[36.8, -1.28], [36.9, -1.29]]},
        {"unknown_setting": 1},
    ],
)
async def test_invalid_values_rejected(client, db, admin, payload):
    r = await client.put(URL, headers=auth_header(admin), json=payload)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "validation_error"
    assert (await db.get(Setting, "commission_bp")).value == 1000


async def test_boundary_values_accepted(client, admin):
    r = await client.put(
        URL, headers=auth_header(admin), json={"commission_percent": 50, "service_fee": 0}
    )
    assert r.status_code == 200
    assert r.json()["commission_percent"] == 50


async def test_hotel_override_falls_back_to_global(db):
    values, _ = await settings.load(db)
    plain = await make_hotel(db)
    custom = await make_hotel(db, commission_bp=800, service_fee=15)
    tiers = settings.effective_for_hotel(values, plain)  # global default: flat tiers (D19)
    assert (tiers.commission_bp, tiers.service_fee, tiers.commission_for(650)) == (0, 20, 30)
    # A per-hotel percent deal overrides the tiers.
    assert settings.effective_for_hotel(values, custom) == settings.HotelRates(
        800, 15, 100, eat_in_fee=30
    )


def test_percent_to_bp():
    assert settings.percent_to_bp(10) == 1000
    assert settings.percent_to_bp("12.5") == 1250
    assert settings.percent_to_bp(0.01) == 1
    with pytest.raises(ValueError):
        settings.percent_to_bp(0.001)


@pytest.mark.parametrize(
    "bands",
    [
        [],
        [{"max_km": 5, "fee": 150}, {"max_km": 2, "fee": 100}],  # not ascending
        [{"max_km": 2, "fee": 100}, {"max_km": 2, "fee": 150}],  # duplicate distance
        [{"max_km": 0, "fee": 100}],
        [{"max_km": 2, "fee": 99.5}],
    ],
)
async def test_rider_fee_bands_validation(client, admin, bands):
    r = await client.put(URL, headers=auth_header(admin), json={"rider_fee_bands": bands})
    assert r.status_code == 422, r.text


async def test_rider_fee_bands_saved(client, admin):
    bands = [{"max_km": 3, "fee": 120}, {"max_km": 8, "fee": 250}]
    r = await client.put(URL, headers=auth_header(admin), json={"rider_fee_bands": bands})
    assert r.status_code == 200, r.text
    assert r.json()["rider_fee_bands"] == [{"max_km": 3.0, "fee": 120}, {"max_km": 8.0, "fee": 250}]


def test_distance_and_band_lookup():
    # Nairobi CBD to Westlands is roughly 3 km in a straight line.
    d = settings.distance_km(-1.2864, 36.8172, -1.2648, 36.8025)
    assert 2.5 < d < 3.5
    bands = settings.DEFAULT_BANDS
    assert settings.rider_fee_for(1.9, bands) == 100
    assert settings.rider_fee_for(2.0, bands) == 100
    assert settings.rider_fee_for(4.2, bands) == 150
    assert settings.rider_fee_for(10.0, bands) == 200
    assert settings.rider_fee_for(10.1, bands) is None


async def test_support_whatsapp(client, admin):
    r = await client.put(URL, headers=auth_header(admin), json={"support_whatsapp": "0712 345 678"})
    assert r.status_code == 200 and r.json()["support_whatsapp"] == "254712345678"
    assert (await client.get("/api/v1/config")).json()["support_whatsapp"] == "254712345678"
    bad = await client.put(URL, headers=auth_header(admin), json={"support_whatsapp": "12345"})
    assert bad.status_code == 422
    r = await client.put(URL, headers=auth_header(admin), json={"support_whatsapp": ""})
    assert r.json()["support_whatsapp"] == ""
    assert (await client.get("/api/v1/config")).json()["support_whatsapp"] is None


def test_per_km_fee_formula():
    s = settings.PlatformSettings(
        rider_fee_mode="per_km",
        rider_fee_base=50,
        rider_fee_per_km=20,
        rider_fee_min=100,
        rider_fee_max_km=10,
    )
    assert s.rider_fee_at(0) == 100  # minimum
    assert s.rider_fee_at(2.5) == 100  # 50 + 50
    assert s.rider_fee_at(3.1) == 120  # 112 -> rounded up to 120
    assert s.rider_fee_at(10) == 250
    assert s.rider_fee_at(10.1) is None  # beyond the furthest distance
    assert s.base_rider_fee == 100
    bands = settings.PlatformSettings(rider_fee_mode="bands")
    assert (bands.rider_fee_at(4), bands.max_delivery_km) == (150, 10)
