from fastapi import APIRouter

from app.api.deps import CurrentUserDep, Session
from app.core.errors import AppError
from app.models import User
from app.schemas.auth import LoginIn, MeOut, RefreshIn, TokenOut
from app.services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


def _out(pair: auth.TokenPair) -> TokenOut:
    return TokenOut(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        user=MeOut.model_validate(pair.user),
    )


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: Session):
    pair = await auth.login(session, body.phone, body.password)
    await session.commit()
    return _out(pair)


@router.post("/refresh", response_model=TokenOut)
async def refresh(body: RefreshIn, session: Session):
    try:
        pair = await auth.refresh(session, body.refresh_token)
    except auth.RefreshReused:
        await session.commit()  # keep the revocation of every session
        raise AppError(401, "invalid_refresh", "Please log in again") from None
    await session.commit()
    return _out(pair)


@router.post("/logout", status_code=204)
async def logout(body: RefreshIn, session: Session):
    await auth.logout(session, body.refresh_token)
    await session.commit()


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUserDep, session: Session):
    """Who is logged in. Also used by live screens to refresh an expired access token."""
    return MeOut.model_validate(await session.get(User, user.id))
