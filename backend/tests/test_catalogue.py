"""M2 acceptance: a hotel manages its full menu; another hotel cannot see or edit it."""

import io
import uuid
from datetime import UTC, datetime, time, timedelta

import pytest
from PIL import Image

from app.main import app
from app.models import Hotel, HotelHours
from app.services import media
from app.services.hours import open_status
from tests.factories import auth_header, make_hotel, make_user

API = "/api/v1/hotel"


class MemoryStorage:
    def __init__(self):
        self.files: dict[str, bytes] = {}

    def put(self, key, data, content_type):
        self.files[key] = data

    def url(self, key):
        return f"https://cdn.test/{key}"


@pytest.fixture
def storage():
    s = MemoryStorage()
    app.dependency_overrides[media.get_storage] = lambda: s
    yield s
    app.dependency_overrides.pop(media.get_storage, None)


@pytest.fixture
async def hotel_a(db):
    hotel = await make_hotel(db, slug="hotel-a")
    return hotel, auth_header(await make_user(db, "hotel_admin", hotel))


@pytest.fixture
async def hotel_b(db):
    hotel = await make_hotel(db, slug="hotel-b")
    return hotel, auth_header(await make_user(db, "hotel_admin", hotel))


def jpeg_with_exif() -> bytes:
    img = Image.new("RGB", (2000, 1500), (200, 80, 20))
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # Make
    exif[0x8825] = {2: (1.0, 17.0, 0.0)}  # GPS
    out = io.BytesIO()
    img.save(out, "JPEG", exif=exif)
    return out.getvalue()


async def build_menu(client, headers, storage):
    cat = (await client.post(f"{API}/categories", headers=headers, json={"name": "Mains"})).json()
    up = await client.post(
        f"{API}/uploads/image",
        headers=headers,
        files={"file": ("pilau.jpg", jpeg_with_exif(), "image/jpeg")},
    )
    assert up.status_code == 201, up.text
    product = await client.post(
        f"{API}/products",
        headers=headers,
        json={
            "category_id": cat["id"],
            "name": "Pilau",
            "price": 650,
            "image_key": up.json()["image_key"],
        },
    )
    assert product.status_code == 201, product.text
    pid = product.json()["id"]
    opt = await client.post(
        f"{API}/products/{pid}/options",
        headers=headers,
        json={"group_name": "Extras", "name": "Kachumbari", "price_delta": 30},
    )
    assert opt.status_code == 201
    return cat, product.json(), opt.json()


# --- Full menu flow -----------------------------------------------------------------------------


async def test_hotel_builds_menu_and_customers_see_it(client, hotel_a, storage):
    hotel, headers = hotel_a
    _, product, option = await build_menu(client, headers, storage)
    assert product["thumb_url"].endswith("-thumb.webp")

    menu = (await client.get(f"/api/v1/hotels/{hotel.slug}/menu")).json()
    (category,) = menu["categories"]
    (item,) = category["products"]
    assert item["name"] == "Pilau"
    assert item["price"] == 650
    assert item["options"][0]["id"] == option["id"]


async def test_images_are_webp_resized_and_stripped(client, hotel_a, storage):
    _, headers = hotel_a
    r = await client.post(
        f"{API}/uploads/image",
        headers=headers,
        files={"file": ("x.jpg", jpeg_with_exif(), "image/jpeg")},
    )
    body = r.json()
    full = Image.open(io.BytesIO(storage.files[body["image_key"]]))
    thumb = Image.open(io.BytesIO(storage.files[body["thumb_key"]]))
    assert full.format == thumb.format == "WEBP"
    assert max(full.size) == media.FULL_SIZE
    assert max(thumb.size) == media.THUMB_SIZE
    assert not full.getexif()
    assert body["image_key"].startswith(f"hotels/{hotel_a[0].id}/")


async def test_non_image_upload_rejected(client, hotel_a, storage):
    _, headers = hotel_a
    r = await client.post(
        f"{API}/uploads/image",
        headers=headers,
        files={"file": ("evil.jpg", b"<?php echo 1; ?>", "image/jpeg")},
    )
    assert r.status_code == 422
    assert storage.files == {}


async def test_sold_out_and_archive(client, hotel_a, storage):
    hotel, headers = hotel_a
    _, product, _ = await build_menu(client, headers, storage)
    await client.patch(
        f"{API}/products/{product['id']}", headers=headers, json={"is_sold_out": True}
    )
    item = (await client.get(f"/api/v1/hotels/{hotel.slug}/menu")).json()["categories"][0][
        "products"
    ][0]
    assert item["is_sold_out"] is True  # still listed, greyed by the app

    await client.patch(
        f"{API}/products/{product['id']}", headers=headers, json={"is_archived": True}
    )
    menu = (await client.get(f"/api/v1/hotels/{hotel.slug}/menu")).json()
    assert menu["categories"] == []  # archived products and empty categories are hidden


async def test_archived_options_hidden_from_customers(client, hotel_a, storage):
    hotel, headers = hotel_a
    _, product, option = await build_menu(client, headers, storage)
    await client.patch(
        f"{API}/products/{product['id']}/options/{option['id']}",
        headers=headers,
        json={"is_archived": True},
    )
    item = (await client.get(f"/api/v1/hotels/{hotel.slug}/menu")).json()["categories"][0][
        "products"
    ][0]
    assert item["options"] == []


async def test_menu_etag(client, hotel_a, storage):
    hotel, headers = hotel_a
    _, product, _ = await build_menu(client, headers, storage)
    url = f"/api/v1/hotels/{hotel.slug}/menu"
    first = await client.get(url)
    etag = first.headers["etag"]
    again = await client.get(url, headers={"If-None-Match": etag})
    assert again.status_code == 304
    await client.patch(f"{API}/products/{product['id']}", headers=headers, json={"price": 700})
    changed = await client.get(url, headers={"If-None-Match": etag})
    assert changed.status_code == 200
    assert changed.headers["etag"] != etag


async def test_item_discount_price_shown(client, hotel_a, storage):
    hotel, headers = hotel_a
    _, product, _ = await build_menu(client, headers, storage)
    r = await client.post(
        f"{API}/discounts",
        headers=headers,
        json={
            "scope": "item",
            "product_id": product["id"],
            "kind": "percent",
            "percent": 10,
            "starts_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["value"] == 1000
    item = (await client.get(f"/api/v1/hotels/{hotel.slug}/menu")).json()["categories"][0][
        "products"
    ][0]
    assert item["discount_price"] == 585


# --- Validation ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "X", "price": 10.5},
        {"name": "X", "price": -1},
        {"name": "", "price": 10},
        {"name": "X", "price": 10, "unexpected": 1},
    ],
)
async def test_product_validation(client, hotel_a, payload):
    _, headers = hotel_a
    cat = (await client.post(f"{API}/categories", headers=headers, json={"name": "C"})).json()
    r = await client.post(
        f"{API}/products", headers=headers, json={"category_id": cat["id"], **payload}
    )
    assert r.status_code == 422


async def test_duplicate_category_and_delete_rules(client, hotel_a, storage):
    _, headers = hotel_a
    cat, _, _ = await build_menu(client, headers, storage)
    dup = await client.post(f"{API}/categories", headers=headers, json={"name": "Mains"})
    assert dup.status_code == 409
    in_use = await client.delete(f"{API}/categories/{cat['id']}", headers=headers)
    assert in_use.status_code == 409
    empty = (await client.post(f"{API}/categories", headers=headers, json={"name": "E"})).json()
    assert (
        await client.delete(f"{API}/categories/{empty['id']}", headers=headers)
    ).status_code == 204


@pytest.mark.parametrize(
    "payload",
    [
        {"scope": "order", "kind": "percent", "percent": 100.5},
        {"scope": "order", "kind": "percent", "amount": 50},
        {"scope": "order", "kind": "fixed", "amount": 0},
        {"scope": "item", "kind": "fixed", "amount": 50},  # item without product
        {"scope": "order", "kind": "fixed", "amount": 50, "promo_code": "a b"},
        {"scope": "order", "kind": "fixed", "amount": 50, "max_uses": 5},  # limit w/o code
    ],
)
async def test_discount_validation(client, hotel_a, payload):
    _, headers = hotel_a
    r = await client.post(
        f"{API}/discounts", headers=headers, json={"starts_at": "2026-10-01T00:00:00Z", **payload}
    )
    assert r.status_code == 422, r.text


async def test_promo_codes_unique_per_hotel_and_uppercased(client, hotel_a, hotel_b):
    body = {
        "scope": "order",
        "kind": "fixed",
        "amount": 50,
        "promo_code": "karibu",
        "starts_at": "2026-10-01T00:00:00Z",
    }
    r = await client.post(f"{API}/discounts", headers=hotel_a[1], json=body)
    assert r.json()["promo_code"] == "KARIBU"
    assert (await client.post(f"{API}/discounts", headers=hotel_a[1], json=body)).status_code == 409
    assert (await client.post(f"{API}/discounts", headers=hotel_b[1], json=body)).status_code == 201


# --- Isolation between hotels -------------------------------------------------------------------


async def test_other_hotel_cannot_see_or_edit(client, hotel_a, hotel_b, storage):
    _, headers_a = hotel_a
    _, headers_b = hotel_b
    cat, product, option = await build_menu(client, headers_a, storage)

    assert (await client.get(f"{API}/products", headers=headers_b)).json() == []
    assert (await client.get(f"{API}/categories", headers=headers_b)).json() == []
    for method, url, body in [
        ("get", f"{API}/products/{product['id']}", None),
        ("patch", f"{API}/products/{product['id']}", {"price": 1}),
        ("patch", f"{API}/categories/{cat['id']}", {"name": "Hacked"}),
        ("delete", f"{API}/categories/{cat['id']}", None),
        ("get", f"{API}/products/{product['id']}/options", None),
        ("patch", f"{API}/products/{product['id']}/options/{option['id']}", {"price_delta": 0}),
        ("post", f"{API}/products/{product['id']}/options", {"group_name": "G", "name": "N"}),
    ]:
        kwargs = {"headers": headers_b} | ({"json": body} if body else {})
        r = await getattr(client, method)(url, **kwargs)
        assert r.status_code == 404, (method, url, r.status_code)

    # B cannot put A's product or category into its own records either.
    r = await client.post(
        f"{API}/products",
        headers=headers_b,
        json={"category_id": cat["id"], "name": "X", "price": 1},
    )
    assert r.status_code == 404
    r = await client.post(
        f"{API}/discounts",
        headers=headers_b,
        json={
            "scope": "item",
            "product_id": product["id"],
            "kind": "fixed",
            "amount": 5,
            "starts_at": "2026-10-01T00:00:00Z",
        },
    )
    assert r.status_code == 404
    r = await client.post(
        f"{API}/products",
        headers=headers_b,
        json={
            "category_id": str(uuid.uuid4()),
            "name": "X",
            "price": 1,
            "image_key": product["thumb_url"].split("cdn.test/")[1],
        },
    )
    assert r.status_code in (404, 422)

    # And A's menu is unchanged.
    assert (await client.get(f"{API}/products/{product['id']}", headers=headers_a)).json()[
        "price"
    ] == 650


async def test_cannot_use_another_hotels_photo(client, hotel_a, hotel_b, storage):
    _, headers_a = hotel_a
    _, headers_b = hotel_b
    key = (
        await client.post(
            f"{API}/uploads/image",
            headers=headers_a,
            files={"file": ("x.jpg", jpeg_with_exif(), "image/jpeg")},
        )
    ).json()["image_key"]
    cat = (await client.post(f"{API}/categories", headers=headers_b, json={"name": "C"})).json()
    r = await client.post(
        f"{API}/products",
        headers=headers_b,
        json={"category_id": cat["id"], "name": "X", "price": 1, "image_key": key},
    )
    assert r.status_code == 422


# --- Cashier limits -----------------------------------------------------------------------------


async def test_cashier_can_only_toggle_sold_out_and_accepting(client, db, hotel_a, storage):
    hotel, admin_headers = hotel_a
    _, product, _ = await build_menu(client, admin_headers, storage)
    cashier = auth_header(await make_user(db, "cashier", hotel))
    url = f"{API}/products/{product['id']}"
    assert (await client.patch(url, headers=cashier, json={"is_sold_out": True})).status_code == 200
    assert (await client.patch(url, headers=cashier, json={"price": 1})).status_code == 403
    assert (
        await client.post(f"{API}/categories", headers=cashier, json={"name": "Z"})
    ).status_code == 403
    r = await client.put(f"{API}/settings", headers=cashier, json={"accepting_orders": False})
    assert r.status_code == 200 and r.json()["accepting_orders"] is False
    r = await client.put(f"{API}/settings", headers=cashier, json={"cash_pickup_enabled": False})
    assert r.status_code == 403


# --- Hours and open status ----------------------------------------------------------------------


async def test_hours_replace_and_public_open_state(client, hotel_a, storage):
    hotel, headers = hotel_a
    every_day = [{"weekday": d, "opens_at": "00:00", "closes_at": "23:59"} for d in range(7)]
    r = await client.put(f"{API}/settings", headers=headers, json={"hours": every_day})
    assert r.status_code == 200 and len(r.json()["hours"]) == 7
    hotels = {h["slug"]: h for h in (await client.get("/api/v1/hotels")).json()}
    assert hotels[hotel.slug]["state"] in ("open", "closing_soon", "closed")

    r = await client.put(f"{API}/settings", headers=headers, json={"hours": []})
    assert r.json()["hours"] == []
    hotels = {h["slug"]: h for h in (await client.get("/api/v1/hotels")).json()}
    assert hotels[hotel.slug]["state"] == "closed"


def _hours(opens: str, closes: str) -> list[HotelHours]:
    return [
        HotelHours(
            weekday=d, opens_at=time.fromisoformat(opens), closes_at=time.fromisoformat(closes)
        )
        for d in range(7)
    ]


def _at(hh: int, mm: int = 0) -> datetime:
    # 2026-10-02 is a Friday; Nairobi is UTC+3.
    return datetime(2026, 10, 2, hh, mm, tzinfo=UTC) - timedelta(hours=3)


@pytest.mark.parametrize(
    ("opens", "closes", "local", "state"),
    [
        ("08:00", "22:00", (12, 0), "open"),
        ("08:00", "22:00", (21, 30), "closing_soon"),  # 30 min before the 21:45 cut-off
        ("08:00", "22:00", (21, 50), "closed"),  # inside the 15-minute cut-off
        ("08:00", "22:00", (7, 59), "closed"),
        ("18:00", "02:00", (1, 0), "open"),  # overnight window from the previous day
        ("18:00", "02:00", (3, 0), "closed"),
    ],
)
def test_open_status(opens, closes, local, state):
    hotel = Hotel(status="active", accepting_orders=True)
    assert open_status(hotel, _hours(opens, closes), _at(*local), 15).state == state


def test_paused_and_not_accepting():
    hours = _hours("00:00", "23:59")
    assert open_status(Hotel(status="paused", accepting_orders=True), hours, _at(12), 15).state == (
        "paused"
    )
    assert open_status(
        Hotel(status="active", accepting_orders=False), hours, _at(12), 15
    ).state == ("not_accepting")


async def test_hotel_sets_its_location(client, hotel_a):
    hotel, headers = hotel_a
    r = await client.put(f"{API}/settings", headers=headers, json={"lat": -1.28, "lng": 36.82})
    assert r.status_code == 200 and (r.json()["lat"], r.json()["lng"]) == (-1.28, 36.82)
    bad = await client.put(f"{API}/settings", headers=headers, json={"lat": -1.28})
    assert bad.status_code == 422
    menu = (await client.get(f"/api/v1/hotels/{hotel.slug}/menu")).json()
    assert menu["hotel"]["lat"] == -1.28
