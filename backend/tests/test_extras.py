"""Extras: a hotel's shared groups (required, pick-one, up-to-N) attached to many dishes."""

import uuid

import pytest

from app.api.v1 import ordering
from app.services.pricing import (
    CartLine,
    GroupRule,
    OptionInfo,
    PricingError,
    ProductInfo,
)
from tests.factories import NOW, auth_header, make_product, make_user
from tests.test_ordering import open_hotel, set_zone
from tests.test_pricing import quote

API = "/api/v1/hotel"


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    monkeypatch.setattr(ordering, "utcnow", lambda: NOW)


# --- The rules, in the pure price calculation ----------------------------------------------------

SMALL = OptionInfo(uuid.uuid4(), "Size", "Small", 0)
LARGE = OptionInfo(uuid.uuid4(), "Size", "Large", 200)
CHEESE = OptionInfo(uuid.uuid4(), "Toppings", "Cheese", 100)
HONEY = OptionInfo(uuid.uuid4(), "Toppings", "Honey", 50)
CHILLI = OptionInfo(uuid.uuid4(), "Toppings", "Chilli", 0)
GONE = OptionInfo(uuid.uuid4(), "Toppings", "Olives", 70, is_sold_out=True)
PIZZA = ProductInfo(
    uuid.uuid4(),
    "Pizza",
    800,
    options={o.id: o for o in (SMALL, LARGE, CHEESE, HONEY, CHILLI, GONE)},
    groups=(
        GroupRule("Size", frozenset({SMALL.id, LARGE.id}), min_picks=1, max_picks=1),
        GroupRule("Toppings", frozenset({CHEESE.id, HONEY.id, CHILLI.id, GONE.id}), max_picks=2),
    ),
)


def pizza(*opts, qty=1):
    return quote([CartLine(PIZZA.id, qty, tuple(o.id for o in opts))], products={PIZZA.id: PIZZA})


def test_required_group_needs_a_pick():
    with pytest.raises(PricingError) as e:
        pizza(CHEESE)
    assert e.value.code == "option_required"
    assert "Size" in e.value.message


def test_pick_one_group_refuses_two():
    with pytest.raises(PricingError) as e:
        pizza(SMALL, LARGE)
    assert e.value.code == "option_too_many"


def test_up_to_two_toppings():
    q = pizza(LARGE, CHEESE, HONEY, qty=2)
    assert q.items_total == (800 + 200 + 100 + 50) * 2
    with pytest.raises(PricingError) as e:
        pizza(LARGE, CHEESE, HONEY, CHILLI)
    assert e.value.code == "option_too_many"


def test_optional_group_may_be_skipped_and_finished_extra_is_refused():
    assert pizza(SMALL).items_total == 800
    with pytest.raises(PricingError) as e:
        pizza(SMALL, GONE)
    assert e.value.code == "option_sold_out"


# --- The hotel's side and the customer's, through the API ---------------------------------------


async def setup(client, db):
    hotel, pilau = await open_hotel(db)
    await set_zone(db)
    chapati = await make_product(db, hotel, price=50, name="Chapati")
    admin = auth_header(await make_user(db, "hotel_admin", hotel))
    await db.commit()
    return hotel, pilau, chapati, admin


def lines(product, *option_ids):
    return [{"product_id": str(product.id), "quantity": 1, "option_ids": [str(o) for o in option_ids]}]


async def ask(client, hotel, product, *option_ids):
    return await client.post(
        "/api/v1/quotes",
        json={
            "hotel_slug": hotel.slug,
            "lines": lines(product, *option_ids),
            "type": "pickup",
            "rider_fee_mode": "none",
        },
    )


async def test_group_is_built_once_and_attached_to_many_dishes(client, db):
    hotel, pilau, chapati, admin = await setup(client, db)
    r = await client.post(
        f"{API}/extras",
        headers=admin,
        json={
            "name": "Sides",
            "min_picks": 1,
            "max_picks": 1,
            "items": [{"name": "Kachumbari", "price_delta": 30}, {"name": "Beans", "price_delta": 40}],
            "product_ids": [str(pilau.id), str(chapati.id)],
        },
    )
    assert r.status_code == 201, r.text
    group = r.json()
    assert sorted(group["product_ids"]) == sorted([str(pilau.id), str(chapati.id)])
    beans, kachumbari = sorted(group["items"], key=lambda i: i["name"])

    menu = (await client.get(f"/api/v1/hotels/{hotel.slug}/menu")).json()
    for item in menu["categories"][0]["products"]:
        (g,) = item["extra_groups"]
        assert (g["name"], g["min_picks"], g["max_picks"]) == ("Sides", 1, 1)
        assert len(item["options"]) == 2  # older apps still get one flat list

    # Required: no pick is refused, one pick is priced, two picks are refused.
    assert (await ask(client, hotel, pilau)).status_code == 422
    ok = await ask(client, hotel, pilau, kachumbari["id"])
    assert ok.status_code == 200, ok.text
    assert ok.json()["items_total"] == 650 + 30
    assert (await ask(client, hotel, pilau, kachumbari["id"], beans["id"])).status_code == 422

    # One price change reaches every dish.
    r = await client.patch(
        f"{API}/extras/{group['id']}/items/{kachumbari['id']}", headers=admin, json={"price_delta": 35}
    )
    assert r.status_code == 200
    assert (await ask(client, hotel, chapati, kachumbari["id"])).json()["items_total"] == 50 + 35


async def test_finished_extra_vanishes_for_everyone_and_cannot_block_the_dish(client, db):
    hotel, pilau, _, admin = await setup(client, db)
    group = (
        await client.post(
            f"{API}/extras",
            headers=admin,
            json={
                "name": "Sauce",
                "min_picks": 1,
                "items": [{"name": "Pili pili"}],
                "product_ids": [str(pilau.id)],
            },
        )
    ).json()
    (item,) = group["items"]
    await client.patch(
        f"{API}/extras/{group['id']}/items/{item['id']}", headers=admin, json={"is_sold_out": True}
    )
    menu = (await client.get(f"/api/v1/hotels/{hotel.slug}/menu")).json()
    dishes = [p for c in menu["categories"] for p in c["products"]]
    shown = next(p for p in dishes if p["name"] == "Pilau")
    (g,) = shown["extra_groups"]
    assert g["min_picks"] == 0  # nothing left to choose, so the dish can still be ordered
    assert g["options"][0]["is_sold_out"] is True
    assert (await ask(client, hotel, pilau)).status_code == 200
    assert (await ask(client, hotel, pilau, item["id"])).status_code == 422


async def test_attach_from_the_dish_and_delete_the_group(client, db):
    hotel, pilau, chapati, admin = await setup(client, db)
    group = (
        await client.post(
            f"{API}/extras", headers=admin, json={"name": "Drinks", "items": [{"name": "Soda", "price_delta": 60}]}
        )
    ).json()
    r = await client.put(f"{API}/products/{chapati.id}/extras", headers=admin, json={"group_ids": [group["id"]]})
    assert r.status_code == 200 and r.json() == [group["id"]]
    product = (await client.get(f"{API}/products/{chapati.id}", headers=admin)).json()
    assert product["extra_group_ids"] == [group["id"]]
    assert (await client.get(f"{API}/extras", headers=admin)).json()[0]["product_ids"] == [str(chapati.id)]

    assert (await client.delete(f"{API}/extras/{group['id']}", headers=admin)).status_code == 204
    assert (await client.get(f"{API}/extras", headers=admin)).json() == []
    shown = (await client.get(f"/api/v1/hotels/{hotel.slug}/menu")).json()
    assert all(p["extra_groups"] == [] for c in shown["categories"] for p in c["products"])


async def test_extras_are_private_to_their_hotel_and_rules_are_checked(client, db):
    hotel, pilau, _, admin = await setup(client, db)
    other, other_dish = await open_hotel(db, slug="other-hotel")
    other_admin = auth_header(await make_user(db, "hotel_admin", other))
    await db.commit()
    group = (await client.post(f"{API}/extras", headers=admin, json={"name": "Mine"})).json()
    assert (await client.get(f"{API}/extras", headers=other_admin)).json() == []
    assert (await client.delete(f"{API}/extras/{group['id']}", headers=other_admin)).status_code == 404
    # A hotel cannot attach a group to another hotel's dish.
    r = await client.put(f"{API}/products/{other_dish.id}/extras", headers=admin, json={"group_ids": [group["id"]]})
    assert r.status_code == 404
    bad = await client.post(f"{API}/extras", headers=admin, json={"name": "Bad", "min_picks": 3, "max_picks": 2})
    assert bad.status_code == 422
    dup = await client.post(f"{API}/extras", headers=admin, json={"name": "Mine"})
    assert dup.status_code == 409
