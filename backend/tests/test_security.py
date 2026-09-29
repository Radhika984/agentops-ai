from __future__ import annotations

import time
import uuid

import jwt
import pytest

from app.core import security
from app.core.config import settings


def test_hash_password_differs_from_plaintext() -> None:
    hashed = security.hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"


def test_verify_password_correct() -> None:
    hashed = security.hash_password("correct horse battery staple")
    assert security.verify_password("correct horse battery staple", hashed) is True


def test_verify_password_incorrect() -> None:
    hashed = security.hash_password("correct horse battery staple")
    assert security.verify_password("wrong password", hashed) is False


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    token = security.create_access_token(user_id)
    assert security.decode_access_token(token) == user_id


def test_expired_token_rejected() -> None:
    now = int(time.time())
    payload = {
        "sub": str(uuid.uuid4()),
        "type": "access",
        "iat": now - 120,
        "exp": now - 60,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token)


def test_malformed_token_rejected() -> None:
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token("not-a-real-token")


def test_wrong_token_type_rejected() -> None:
    now = int(time.time())
    payload = {
        "sub": str(uuid.uuid4()),
        "type": "refresh",
        "iat": now,
        "exp": now + 3600,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(security.InvalidTokenError):
        security.decode_access_token(token)
