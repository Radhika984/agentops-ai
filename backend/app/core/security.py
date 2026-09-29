from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()  # argon2


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


ACCESS_TOKEN_TYPE = "access"


def create_access_token(user_id: uuid.UUID | str) -> str:
    now = datetime.now(UTC)
    expire = now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "type": ACCESS_TOKEN_TYPE,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


class InvalidTokenError(Exception):
    """Raised when a JWT is missing, malformed, expired, or the wrong type."""


def decode_access_token(token: str) -> uuid.UUID:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("Invalid or expired token") from exc

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise InvalidTokenError("Incorrect token type")

    sub = payload.get("sub")
    if not sub:
        raise InvalidTokenError("Token missing subject")

    try:
        return uuid.UUID(sub)
    except (ValueError, TypeError) as exc:
        raise InvalidTokenError("Token subject is not a valid UUID") from exc
