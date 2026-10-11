"""The short-lived caches in front of the database must never serve a change late in the worker
that made it: a deactivated account is refused at once, a changed setting applies at once."""

from app.services import settings
from tests.factories import auth_header, make_hotel, make_user

API = "/api/v1"


async def test_deactivated_user_is_refused_straight_away(client, db):
    hotel = await make_hotel(db)
    admin = await make_user(db, "hotel_admin", hotel)
    h = auth_header(admin)
    assert (await client.get(f"{API}/hotel/categories", headers=h)).status_code == 200
    assert (await client.get(f"{API}/hotel/categories", headers=h)).status_code == 200  # cached

    admin.is_active = False
    await db.flush()
    assert (await client.get(f"{API}/hotel/categories", headers=h)).status_code == 401


async def test_settings_change_shows_at_once(db):
    before, _ = await settings.load(db)
    await settings.load(db)  # now cached
    await settings.update(db, {"bonus_daily_budget": before.bonus_daily_budget + 1234}, None)
    after, _ = await settings.load(db)
    assert after.bonus_daily_budget == before.bonus_daily_budget + 1234


async def test_callers_cannot_change_the_cached_settings(db):
    a, _ = await settings.load(db)
    a.bonus_daily_budget = -1
    b, _ = await settings.load(db)
    assert b.bonus_daily_budget != -1
