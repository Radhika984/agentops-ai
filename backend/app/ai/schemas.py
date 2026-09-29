from __future__ import annotations

from pydantic import BaseModel, Field


class AnswerResponse(BaseModel):
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
