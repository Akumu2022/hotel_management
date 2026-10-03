"""Hotel scoping (spec section 4): another hotel's data is indistinguishable from missing data."""

import uuid

import pytest

from tests.factories import auth_header, make_category, make_hotel, make_user


@pytest.fixture
async def two_hotels(db):
    a, b = await make_hotel(db), await make_hotel(db)
    cat_a = await make_category(db, a, "A mains")
    cat_b = await make_category(db, b, "B mains")
    return a, b, cat_a, cat_b


@pytest.mark.parametrize("role", ["hotel_admin", "cashier"])
async def test_cross_hotel_read_is_404(client, db, two_hotels, role):
    a, _, cat_a, cat_b = two_hotels
    headers = auth_header(await make_user(db, role, a))

    own = await client.get(f"/api/v1/hotel/categories/{cat_a.id}", headers=headers)
    assert own.status_code == 200
    other = await client.get(f"/api/v1/hotel/categories/{cat_b.id}", headers=headers)
    missing = await client.get(f"/api/v1/hotel/categories/{uuid.uuid4()}", headers=headers)
    assert other.status_code == missing.status_code == 404
    assert other.json() == missing.json()


async def test_list_only_shows_own_hotel(client, db, two_hotels):
    a, _, cat_a, _ = two_hotels
    headers = auth_header(await make_user(db, "hotel_admin", a))
    r = await client.get("/api/v1/hotel/categories", headers=headers)
    assert [c["id"] for c in r.json()] == [str(cat_a.id)]


@pytest.mark.parametrize("role", ["super_admin", "rider"])
async def test_non_hotel_roles_cannot_use_hotel_area(client, db, role):
    headers = auth_header(await make_user(db, role))
    assert (await client.get("/api/v1/hotel/categories", headers=headers)).status_code == 403


@pytest.mark.parametrize("role", ["hotel_admin", "cashier", "rider"])
async def test_only_super_admin_reaches_admin_area(client, db, role):
    hotel = await make_hotel(db)
    user = await make_user(db, role, hotel if role != "rider" else None)
    headers = auth_header(user)
    for path in ("/api/v1/admin/settings", "/api/v1/admin/hotels", "/api/v1/admin/users"):
        assert (await client.get(path, headers=headers)).status_code == 403


async def test_hotel_role_requires_hotel_in_database(db):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await make_user(db, "cashier", None)
