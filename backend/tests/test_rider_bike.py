"""Rider security: the bike's number plate and description are required; the logbook is optional."""

from sqlalchemy import func, select

from app.models import RiderProfile, User
from tests.factories import auth_header, make_user
from tests.test_catalogue import jpeg_with_exif
from tests.test_riders import DETAILS, apply, applied, photos, stores  # noqa: F401  (fixture)

API = "/api/v1"


async def rider_count(db):
    return await db.scalar(select(func.count()).select_from(User).where(User.role == "rider"))


async def test_the_plate_is_tidied_up_and_saved_with_the_description(client, db, stores):
    h = await applied(client, bike_plate=" kmfb-123c ")
    me = (await client.get(f"{API}/rider/me", headers=h)).json()
    assert me["bike_plate"] == "KMFB123C"
    assert me["bike_description"] == DETAILS["bike_description"]


async def test_a_missing_plate_or_description_is_refused(client, db, stores):
    for field in ("bike_plate", "bike_description"):
        data = {k: v for k, v in DETAILS.items() if k != field}
        r = await client.post(f"{API}/riders/apply", data=data, files=photos())
        assert r.status_code == 422, field
        assert await rider_count(db) == 0


async def test_the_logbook_is_optional(client, db, stores):
    _, private = stores
    h = await applied(client)  # no logbook
    me = (await client.get(f"{API}/rider/me", headers=h)).json()
    assert me["photos"]["logbook"] is False and me["kyc_status"] == "pending"
    assert len(private.files) == 3


async def test_a_logbook_photo_is_kept_privately_and_only_the_admin_can_see_it(client, db, stores):
    public, private = stores
    files = photos(logbook=("logbook.jpg", jpeg_with_exif(), "image/jpeg"))
    h = await applied(client, files=files)
    me = (await client.get(f"{API}/rider/me", headers=h)).json()
    assert me["photos"]["logbook"] is True
    assert len(private.files) == 4
    assert all("logbook" not in k for k in public.files)  # never in the public store

    admin = auth_header(await make_user(db, "super_admin"))
    rid = (await client.get(f"{API}/admin/riders?status=pending", headers=admin)).json()[0]["id"]
    seen = await client.get(f"{API}/admin/riders/{rid}/kyc/logbook", headers=admin)
    assert seen.status_code == 200 and seen.headers["cache-control"] == "no-store"
    detail = (await client.get(f"{API}/admin/riders/{rid}", headers=admin)).json()
    assert (detail["bike_plate"], detail["bike_description"]) == ("KMFB123C", DETAILS["bike_description"])
    # A rider (or anyone who is not a super admin) cannot open it.
    assert (await client.get(f"{API}/admin/riders/{rid}/kyc/logbook", headers=h)).status_code == 403


async def test_an_unreadable_logbook_is_refused_and_nothing_is_created(client, db, stores):
    r = await apply(client, files=photos(logbook=("l.jpg", b"not a photo", "image/jpeg")))
    assert r.status_code == 422
    assert (r.json()["error"]["code"], r.json()["error"]["field"]) == ("bad_photo", "logbook")
    assert await rider_count(db) == 0


async def test_a_rider_can_fix_the_bike_while_the_application_is_open(client, db, stores):
    admin = auth_header(await make_user(db, "super_admin"))
    h = await applied(client)
    rid = (await client.get(f"{API}/admin/riders?status=pending", headers=admin)).json()[0]["id"]
    await client.post(f"{API}/admin/riders/{rid}/review", headers=admin, json={"action": "reject", "note": "Plate is wrong"})
    r = await client.patch(f"{API}/rider/me", headers=h, json={"bike_plate": "kmgb 456a", "bike_description": "Blue TVS"})
    assert r.status_code == 200, r.text
    assert (r.json()["bike_plate"], r.json()["bike_description"]) == ("KMGB456A", "Blue TVS")
    bad = await client.patch(f"{API}/rider/me", headers=h, json={"bike_plate": "xx"})
    assert bad.status_code == 422


async def test_an_older_draft_without_bike_details_cannot_be_submitted(client, db, stores):
    rider = await make_user(db, "rider")
    db.add(
        RiderProfile(
            user_id=rider.id,
            national_id="29000111",
            mpesa_number=rider.phone,
            next_of_kin="Some One",
            next_of_kin_phone="254700000001",
            residence_area="Kanduyi",
            id_front_key="a",
            id_back_key="b",
            selfie_key="c",
        )
    )
    await db.flush()
    r = await client.post(f"{API}/rider/submit", headers=auth_header(rider), json={"consent": True})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "bike_missing"
