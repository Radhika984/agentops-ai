from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = None


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None
    is_active: bool
    notify_on_suite_run_complete: bool
    notify_on_release_gate: bool
    notify_on_autofix_proposed: bool
    notify_on_approval_decided: bool
    created_at: datetime
    updated_at: datetime


class UserUpdate(BaseModel):
    """Profile settings — the Settings > Profile tab. full_name is the
    only editable profile field that exists on User; email/password have
    their own dedicated, more sensitive flows (email is immutable post
    -registration in this app's model, password goes through
    PasswordChange below, never through this generic update)."""

    full_name: str | None = Field(default=None, max_length=255)


class PasswordChange(BaseModel):
    """Settings > Security tab. Requires the current password (re-auth
    -on-change, not just a bare new value) — the same discipline a
    password field should always have."""

    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class NotificationPreferences(BaseModel):
    """Settings > Notification Preferences tab. Each flag's one real,
    verifiable effect: whether that event type is written to this user's
    own Recent Activity feed at all (see
    app/services/activity_service.py's module docstring for why this app
    scopes 'notifications' to the one real delivery surface it has,
    rather than pretending to control email/push that doesn't exist)."""

    notify_on_suite_run_complete: bool
    notify_on_release_gate: bool
    notify_on_autofix_proposed: bool
    notify_on_approval_decided: bool
