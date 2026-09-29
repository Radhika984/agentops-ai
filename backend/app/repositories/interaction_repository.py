from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.interaction import Interaction


class InteractionRepository:
    """Database access for interactions. No ownership rules, no HTTP concerns."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, project_id: uuid.UUID, prompt: str, response: str) -> Interaction:
        interaction = Interaction(project_id=project_id, prompt=prompt, response=response)
        self._session.add(interaction)
        await self._session.flush()
        await self._session.refresh(interaction)
        return interaction

    async def list_by_project(self, project_id: uuid.UUID) -> list[Interaction]:
        result = await self._session.execute(
            select(Interaction)
            .where(Interaction.project_id == project_id)
            .order_by(Interaction.created_at)
        )
        return list(result.scalars().all())
