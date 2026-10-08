"""D21: rider applications (everything in one submission); only the super admin reviews them and
sees the ID photos."""

import io

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.main import app
from app.models import AuditLog, User
from app.services import media, riders
from tests.factories import auth_header, make_hotel, make_user
from tests.test_catalogue import MemoryStorage, jpeg_with_exif

DETAILS = {
    "name": "Wafula  Simiyu Barasa",
    "phone": "0733111222",
    "password": "rider-pass-123",
    "national_id": "30123456",
    "next_of_kin": "Nafula Barasa",
    "next_of_kin_phone": "0733999888",
    "residence_area": "Kanduyi, near the stage",
    "bike_plate": "KMFB 123C",
    "bike_description": "Red Boxer 150 with a black delivery box",
    "consent": "true",
}


class MemoryPrivate(riders.PrivateStorage):
    def __init__(self):
        self.files: dict[str, bytes] = {}

    def put(self, key, data):
        self.files[key] = data

    def get(self, key):
        return self.files[key]


@pytest.fixture
def stores():
    public, private = MemoryStorage(), MemoryPrivate()
    app.dependency_overrides[media.get_storage] = lambda: public
    app.dependency_overrides[riders.get_private_storage] = lambda: private
    yield public, private
    app.dependency_overrides.pop(media.get_storage, None)
    app.dependency_overrides.pop(riders.get_private_storage, None)


def photos(**override):
    files = {
        k: (f"{k}.jpg", jpeg_with_exif(), "image/jpeg") for k in ("id_front", "id_back", "selfie")
    }
    files.update(override)
    return files


async def apply(client, files=None, **kw):
    return await client.post(
        "/api/v1/riders/apply", data={**DETAILS, **kw}, files=files or photos()
    )


async def applied(client, **kw):
    r = await apply(client, **kw)
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_one_submission_creates_a_pending_application(client, db, stores):
    public, private = stores
    h = await applied(client)
    me = (await client.get("/api/v1/rider/me", headers=h)).json()
    assert (me["name"], me["phone"], me["kyc_status"]) == (
        "Wafula Simiyu Barasa",
        "254733111222",
        "pending",
    )
    assert me["photos"] == {"id_front": True, "id_back": True, "selfie": True, "logbook": False}
    assert "/riders/" in me["photo_url"]
    # ID photos never reach the public store; only the small selfie photo does.
    assert all("id_" not in k for k in public.files) and len(private.files) == 3
    for data in private.files.values():
        assert not Image.open(io.BytesIO(data)).getexif()  # GPS and camera details stripped
    r = await client.patch("/api/v1/rider/me", headers=h, json={"residence_area": "Elsewhere"})
    assert r.status_code == 409  # locked while the team reviews


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"name": "Wafula"}, "name"),  # one name only
        ({"next_of_kin": "Nafula"}, "next_of_kin"),
        ({"national_id": "12AB"}, "national_id"),
        ({"phone": "12345"}, "phone"),
        ({"password": "short"}, "password"),
        ({"bike_plate": "12"}, "bike_plate"),  # no letters
        ({"bike_plate": "KMFB"}, "bike_plate"),  # no digits
        ({"bike_description": "ab"}, "bike_description"),
    ],
)
async def test_field_errors_name_the_field_and_create_nothing(client, db, stores, change, field):
    r = await apply(client, **change)
    assert r.status_code == 422
    assert [f["loc"][-1] for f in r.json()["error"]["fields"]] == [field]
    assert await db.scalar(select(func.count()).select_from(User).where(User.role == "rider")) == 0


@pytest.mark.parametrize(
    ("kw", "files", "code", "field"),
    [
        ({"next_of_kin_phone": "0733111222"}, None, "same_phone", "next_of_kin_phone"),
        ({"consent": "false"}, None, "consent_required", "consent"),
        ({}, photos(id_back=("b.jpg", b"not a photo", "image/jpeg")), "bad_photo", "id_back"),
    ],
)
async def test_business_errors_point_to_the_step(client, db, stores, kw, files, code, field):
    r = await apply(client, files=files, **kw)
    assert (r.status_code, r.json()["error"]["code"], r.json()["error"]["field"]) == (
        422,
        code,
        field,
    )
    assert await db.scalar(select(func.count()).select_from(User).where(User.role == "rider")) == 0


async def test_missing_photo_is_refused(client, stores):
    files = photos()
    del files["selfie"]
    assert (await apply(client, files=files)).status_code == 422


async def test_duplicate_id_or_phone_refused(client, stores):
    await applied(client)
    r = await apply(client, phone="0733000000")
    assert r.status_code == 409 and r.json()["error"]["field"] == "national_id"
    r = await apply(client, national_id="30999999")
    assert r.status_code == 409 and r.json()["error"]["field"] == "phone"


async def test_admin_review_reject_fix_and_approve(client, db, stores):
    h = await applied(client)
    admin = auth_header(await make_user(db, "super_admin"))
    rid = (await client.get("/api/v1/admin/riders?status=pending", headers=admin)).json()[0]["id"]
    photo = await client.get(f"/api/v1/admin/riders/{rid}/kyc/id_front", headers=admin)
    assert photo.status_code == 200 and photo.headers["cache-control"] == "no-store"

    url = f"/api/v1/admin/riders/{rid}/review"
    r = await client.post(url, headers=admin, json={"action": "reject"})
    assert r.json()["error"]["code"] == "reason_required"
    r = await client.post(
        url, headers=admin, json={"action": "reject", "note": "ID back is blurry"}
    )
    assert (r.json()["kyc_status"], r.json()["kyc_note"]) == ("rejected", "ID back is blurry")

    # The rider retakes the photo and sends it again; the admin approves.
    await client.post(
        "/api/v1/rider/kyc/id_back",
        headers=h,
        files={"file": ("p.jpg", jpeg_with_exif(), "image/jpeg")},
    )
    r = await client.post("/api/v1/rider/submit", headers=h, json={"consent": True})
    assert r.json()["kyc_status"] == "pending"
    r = await client.post(url, headers=admin, json={"action": "approve"})
    assert r.json()["kyc_status"] == "approved" and r.json()["reviewed_by_name"]
    actions = (
        (await db.execute(select(AuditLog.action).where(AuditLog.target_id == rid))).scalars().all()
    )
    assert actions == ["rider.reject", "rider.approve"]


async def test_only_super_admin_sees_kyc(client, db, stores):
    h = await applied(client)
    rid = (await client.get("/api/v1/rider/me", headers=h)).json()["id"]
    hotel = await make_hotel(db)
    for headers in (h, auth_header(await make_user(db, "hotel_admin", hotel))):
        assert (
            await client.get(f"/api/v1/admin/riders/{rid}/kyc/selfie", headers=headers)
        ).status_code == 403
        assert (await client.get("/api/v1/admin/riders", headers=headers)).status_code == 403
