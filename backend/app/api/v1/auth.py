from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response

from app.api.deps import CurrentUserDep, Session
from app.core.config import get_config
from app.core.errors import AppError
from app.core.ratelimit import limit
from app.models import User
from app.schemas.auth import ChangePasswordIn, LoginIn, MeOut, RefreshIn, TokenOut
from app.services import audit, auth

router = APIRouter(prefix="/auth", tags=["auth"])


# The refresh token lives in an httpOnly cookie that only /auth endpoints receive.
REFRESH_COOKIE = "chakula_refresh"
COOKIE_PATH = "/api/v1/auth"
RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


def set_refresh_cookie(response: Response, raw: str) -> None:
    cfg = get_config()
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=cfg.refresh_token_days * 86_400,
        path=COOKIE_PATH,
        httponly=True,  # page scripts can't read it
        secure=cfg.cookie_secure,
        samesite="strict",  # never sent from another site
    )


def _out(pair: auth.TokenPair, response: Response) -> TokenOut:
    set_refresh_cookie(response, pair.refresh_token)
    return TokenOut(access_token=pair.access_token, user=MeOut.model_validate(pair.user))


@router.post("/login", response_model=TokenOut, dependencies=[Depends(limit("login", 10))])
async def login(body: LoginIn, session: Session, response: Response):
    pair = await auth.login(session, body.phone, body.password)
    await session.commit()
    return _out(pair, response)


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    session: Session,
    response: Response,
    cookie: RefreshCookie = None,
    body: RefreshIn | None = None,
):
    raw = (body.refresh_token if body else None) or cookie
    if not raw:
        raise AppError(401, "invalid_refresh", "Please log in again")
    try:
        pair = await auth.refresh(session, raw)
    except auth.RefreshReused:
        await session.commit()  # keep the revocation of every session
        raise AppError(401, "invalid_refresh", "Please log in again") from None
    await session.commit()
    return _out(pair, response)


@router.post("/logout", status_code=204)
async def logout(
    session: Session,
    response: Response,
    cookie: RefreshCookie = None,
    body: RefreshIn | None = None,
):
    raw = (body.refresh_token if body else None) or cookie
    if raw:
        await auth.logout(session, raw)
        await session.commit()
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUserDep, session: Session):
    """Who is logged in. Also used by live screens to refresh an expired access token."""
    return MeOut.model_validate(await session.get(User, user.id))


@router.post(
    "/change-password", response_model=TokenOut, dependencies=[Depends(limit("change_pw", 10))]
)
async def change_password(
    body: ChangePasswordIn, user: CurrentUserDep, session: Session, response: Response
):
    """Everyone can change their own password; required after an admin reset."""
    row = await session.get(User, user.id, with_for_update=True)
    pair = await auth.change_password(session, row, body.current_password, body.new_password)
    await audit.log(
        session,
        actor_id=row.id,
        action="user.password_change",
        target_type="user",
        target_id=row.id,
    )
    await session.commit()
    return _out(pair, response)
