import pytest
from sqlalchemy import select

from app.models import AuditLog
from tests.factories import PASSWORD, auth_header, make_hotel, make_user


@pytest.fixture
async def headers(db):
    return auth_header(await make_user(db, "super_admin"))


HOTEL = {
    "name": "Noor Cafe",
    "slug": "noor-cafe",
    "phone": "0712345678",
    "till_number": "123456",
}


async def test_create_hotel_with_override_and_normalized_phone(client, headers):
    r = await client.post(
        "/api/v1/admin/hotels", headers=headers, json={**HOTEL, "commission_percent": 7.5}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["phone"] == "254712345678"
    assert body["commission_percent"] == 7.5
    assert body["service_fee"] is None  # falls back to the global default


async def test_duplicate_slug_and_till(client, headers):
    await client.post("/api/v1/admin/hotels", headers=headers, json=HOTEL)
    r = await client.post(
        "/api/v1/admin/hotels", headers=headers, json={**HOTEL, "till_number": "999999"}
    )
    assert r.status_code == 409
    r = await client.post("/api/v1/admin/hotels", headers=headers, json={**HOTEL, "slug": "other"})
    assert r.status_code == 409


async def test_patch_hotel_clears_override_and_audits(client, db, headers):
    hotel = await make_hotel(db, commission_bp=800)
    r = await client.patch(
        f"/api/v1/admin/hotels/{hotel.id}",
        headers=headers,
        json={"commission_percent": None, "status": "paused", "pause_reason": "overdue"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["commission_percent"] is None
    assert r.json()["status"] == "paused"
    log = (await db.execute(select(AuditLog).where(AuditLog.action == "hotel.update"))).scalar_one()
    assert log.details["commission_bp"] == {"old": 800, "new": None}


async def test_patch_hotel_rejects_null_required_field(client, db, headers):
    hotel = await make_hotel(db)
    r = await client.patch(f"/api/v1/admin/hotels/{hotel.id}", headers=headers, json={"name": None})
    assert r.status_code == 422


async def test_list_hotels_paginates(client, db, headers):
    for _ in range(5):
        await make_hotel(db)
    seen, cursor = [], None
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = (await client.get("/api/v1/admin/hotels", headers=headers, params=params)).json()
        seen += [h["id"] for h in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 5


async def test_create_staff_and_login(client, db, headers):
    hotel = await make_hotel(db)
    r = await client.post(
        "/api/v1/admin/users",
        headers=headers,
        json={
            "role": "cashier",
            "hotel_id": str(hotel.id),
            "name": "Wanjiku",
            "phone": "0722000111",
            "password": PASSWORD,
        },
    )
    assert r.status_code == 201, r.text
    r = await client.post(
        "/api/v1/auth/login", json={"phone": "+254 722 000 111", "password": PASSWORD}
    )
    assert r.status_code == 200
    assert r.json()["user"]["hotel_id"] == str(hotel.id)


@pytest.mark.parametrize(
    "payload",
    [
        {"role": "cashier", "name": "No Hotel", "phone": "0722000112", "password": PASSWORD},
        {"role": "rider", "name": "Rider", "phone": "0722000113", "password": "short"},
        {"role": "rider", "name": "Rider", "phone": "12345", "password": PASSWORD},
        {"role": "chef", "name": "Chef", "phone": "0722000114", "password": PASSWORD},
    ],
)
async def test_create_user_validation(client, headers, payload):
    r = await client.post("/api/v1/admin/users", headers=headers, json=payload)
    assert r.status_code == 422


async def test_deactivating_user_revokes_sessions(client, db, headers):
    rider = await make_user(db, "rider")
    login = await client.post(
        "/api/v1/auth/login", json={"phone": rider.phone, "password": PASSWORD}
    )
    refresh = login.cookies["chakula_refresh"]
    r = await client.patch(
        f"/api/v1/admin/users/{rider.id}", headers=headers, json={"is_active": False}
    )
    assert r.status_code == 200
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 401
