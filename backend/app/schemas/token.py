from __future__ import annotations

import uuid

from pydantic import BaseModel


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: uuid.UUID
    type: str
    iat: int
    exp: int
