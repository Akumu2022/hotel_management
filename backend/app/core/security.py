import hashlib
import secrets
import uuid
from datetime import timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_config
from app.core.time import utcnow

_hasher = PasswordHasher()
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


# A valid hash to verify against when the user does not exist, so login timing is uniform.
DUMMY_HASH = _hasher.hash("not-a-real-password")


def create_access_token(user_id: uuid.UUID, role: str, hotel_id: uuid.UUID | None) -> str:
    cfg = get_config()
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "role": role,
        "hotel_id": str(hotel_id) if hotel_id else None,
        "iat": now,
        "exp": now + timedelta(minutes=cfg.access_token_minutes),
        "type": "access",
    }
    return jwt.encode(payload, cfg.jwt_secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, get_config().jwt_secret, algorithms=[ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return payload


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
