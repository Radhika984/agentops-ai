from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    question: str = Field(min_length=1)


class AskResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    question: str
    answer: str
    confidence: float
    created_at: datetime


class InteractionRead(BaseModel):
    """A past interaction as read back from history.

    Unlike AskResponse, there is no `confidence` field: the Interaction
    model only persists `prompt`/`response` (Phase 2's schema), not the
    model's confidence score, so history entries cannot report one.
    """

    id: uuid.UUID
    project_id: uuid.UUID
    question: str
    answer: str
    created_at: datetime
