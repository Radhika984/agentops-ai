from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import ToolCallRecord
from app.models.tool_call import ToolCall


class ToolCallRepository:
    """Database access for the tool_calls audit log. No ownership rules,
    no HTTP concerns."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_create(self, *, run_id: uuid.UUID, records: list[ToolCallRecord]) -> None:
        for record in records:
            self._session.add(
                ToolCall(
                    run_id=run_id,
                    tool_name=record["tool_name"],
                    input=record["input"],
                    output=record["output"],
                    duration_ms=record["duration_ms"],
                )
            )
        if records:
            await self._session.flush()
