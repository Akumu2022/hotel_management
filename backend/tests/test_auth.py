from datetime import timedelta

import jwt

from app.core.config import get_config
from app.core.security import ALGORITHM
from app.core.time import utcnow
from tests.factories import PASSWORD, make_hotel, make_user


async def login(client, user, password=PASSWORD):
    return await client.post(
        "/api/v1/auth/login", json={"phone": "0" + user.phone[3:], "password": password}
    )


async def test_login_with_local_phone_format(client, db):
    user = await make_user(db, "super_admin")
    r = await login(client, user)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["role"] == "super_admin"
    assert body["access_token"]
    # D29: the refresh token is only an httpOnly cookie, never readable by page scripts.
    assert "refresh_token" not in body
    cookie = r.headers["set-cookie"].lower()
    assert "chakula_refresh=" in cookie and "httponly" in cookie and "samesite=strict" in cookie
    assert "path=/api/v1/auth" in cookie


async def test_wrong_password_and_unknown_user_look_the_same(client, db):
    user = await make_user(db, "super_admin")
    bad = await login(client, user, "wrong-password")
    unknown = await client.post(
        "/api/v1/auth/login", json={"phone": "0799999999", "password": PASSWORD}
    )
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()
    assert bad.json()["error"]["code"] == "invalid_login"


async def test_inactive_user_cannot_log_in(client, db):
    user = await make_user(db, "rider", is_active=False)
    assert (await login(client, user)).status_code == 401


async def test_refresh_rotates_and_reuse_revokes_everything(client, db):
    user = await make_user(db, "rider")
    first = (await login(client, user)).cookies["chakula_refresh"]
    other_session = (await login(client, user)).cookies["chakula_refresh"]

    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert r.status_code == 200
    second = r.cookies["chakula_refresh"]
    assert second != first

    # Replaying the rotated token is treated as theft: every session is revoked.
    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": first})
    assert replay.status_code == 401
    for token in (second, other_session):
        r = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        assert r.status_code == 401


async def test_logout_revokes_refresh_token(client, db):
    user = await make_user(db, "rider")
    token = (await login(client, user)).cookies["chakula_refresh"]
    assert (
        await client.post("/api/v1/auth/logout", json={"refresh_token": token})
    ).status_code == 204
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    assert r.status_code == 401


async def test_expired_access_token(client, db):
    user = await make_user(db, "super_admin")
    token = jwt.encode(
        {
            "sub": str(user.id),
            "role": user.role,
            "type": "access",
            "exp": utcnow() - timedelta(seconds=1),
        },
        get_config().jwt_secret,
        algorithm=ALGORITHM,
    )
    r = await client.get("/api/v1/admin/settings", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "token_expired"


async def test_missing_and_forged_tokens(client, db):
    assert (await client.get("/api/v1/admin/settings")).status_code == 401
    forged = jwt.encode(
        {"sub": "x", "type": "access"},
        "not-the-secret-but-long-enough-for-hs256",
        algorithm=ALGORITHM,
    )
    r = await client.get("/api/v1/admin/settings", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_deactivated_user_token_stops_working(client, db):
    from tests.factories import auth_header

    hotel = await make_hotel(db)
    user = await make_user(db, "cashier", hotel)
    headers = auth_header(user)
    assert (await client.get("/api/v1/hotel/categories", headers=headers)).status_code == 200
    user.is_active = False
    await db.flush()
    assert (await client.get("/api/v1/hotel/categories", headers=headers)).status_code == 401


async def test_browser_session_uses_the_cookie_only(client, db):
    """D29: a browser never handles the refresh token; the cookie does refresh and logout."""
    user = await make_user(db, "super_admin")
    await login(client, user)  # the test client keeps the cookie like a browser
    r = await client.post("/api/v1/auth/refresh")
    assert r.status_code == 200 and "refresh_token" not in r.json()
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
    client.cookies.clear()
    assert (await client.post("/api/v1/auth/refresh")).status_code == 401


async def test_login_attempts_are_limited(client, db):
    user = await make_user(db, "super_admin")
    codes = [(await login(client, user, "wrong-password")).status_code for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429


def test_production_refuses_development_secrets():
    import pytest

    from app.core.config import Config

    Config(app_env="development").check_secrets()  # dev defaults are fine locally
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        Config(app_env="production", cookie_secure=True).check_secrets()
    strong = "x" * 40
    with pytest.raises(RuntimeError, match="COOKIE_SECURE"):
        Config(app_env="production", jwt_secret=strong, forwarder_key=strong).check_secrets()
    Config(
        app_env="production", jwt_secret=strong, forwarder_key=strong, cookie_secure=True
    ).check_secrets()
