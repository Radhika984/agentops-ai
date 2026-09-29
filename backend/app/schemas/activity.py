from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ActivityEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    title: str
    description: str | None
    entity_type: str | None
    entity_id: uuid.UUID | None
    event_metadata: dict[str, Any]
    created_at: datetime
