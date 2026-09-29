from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import FlagRecord
from app.models.flag import Flag


class FlagRepository:
    """Database access for the flags audit log. No ownership rules, no
    HTTP concerns."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def bulk_create(self, *, run_id: uuid.UUID, records: list[FlagRecord]) -> None:
        for record in records:
            self._session.add(
                Flag(
                    run_id=run_id,
                    agent=record["agent"],
                    type=record["type"],
                    severity=record["severity"],
                    details=record["details"],
                )
            )
        if records:
            await self._session.flush()
