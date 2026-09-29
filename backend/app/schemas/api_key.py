from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ApiKeyRead(BaseModel):
    """The safe, list-view shape — never includes the raw key or its
    hash. `key_prefix` is the only fragment of the original secret ever
    shown again after creation, purely so a user can recognize which key
    is which."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    key_prefix: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


class ApiKeyCreateResponse(BaseModel):
    """Returned ONLY once, from the create endpoint — `api_key` is the
    real, raw secret, which this app never stores and can therefore
    never show again. Every other read of this key returns ApiKeyRead
    instead."""

    id: uuid.UUID
    name: str
    key_prefix: str
    api_key: str
    created_at: datetime
