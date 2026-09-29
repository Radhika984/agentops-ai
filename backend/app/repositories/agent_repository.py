from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.project import Project


class AgentRepository:
    """Database access for agents. No ownership rules, no HTTP concerns —
    matches app/repositories/project_repository.py's own convention."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, project_id: uuid.UUID, name: str, description: str | None) -> Agent:
        agent = Agent(project_id=project_id, name=name, description=description)
        self._session.add(agent)
        await self._session.flush()
        await self._session.refresh(agent)
        return agent

    async def list_by_project(self, project_id: uuid.UUID) -> list[Agent]:
        result = await self._session.execute(
            select(Agent).where(Agent.project_id == project_id).order_by(Agent.created_at)
        )
        return list(result.scalars().all())

    async def get_by_id(self, agent_id: uuid.UUID) -> Agent | None:
        result = await self._session.execute(select(Agent).where(Agent.id == agent_id))
        return result.scalar_one_or_none()

    async def count_for_owner(self, owner_id: uuid.UUID) -> int:
        """The dashboard's "Agents" stat tile — every Agent across every
        Project this user owns, via a real join (Agent -> Project), not
        the N-request "flatten every project's agents" pattern the
        frontend uses elsewhere for a full listing (a bare count needs
        no per-agent detail, so one aggregate query is strictly
        better)."""
        result = await self._session.execute(
            select(func.count(Agent.id))
            .join(Project, Project.id == Agent.project_id)
            .where(Project.owner_id == owner_id)
        )
        return int(result.scalar_one())

    async def update(self, agent: Agent, **fields: Any) -> Agent:
        for key, value in fields.items():
            setattr(agent, key, value)
        await self._session.flush()
        await self._session.refresh(agent)
        return agent
