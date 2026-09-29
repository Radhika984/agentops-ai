from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_version import AgentVersion


class AgentVersionRepository:
    """Database access for agent versions. No ownership rules, no HTTP
    concerns — matches app/repositories/project_repository.py's own
    convention. Baseline promotion's two-step unset/set (see
    services/agent_service.py) lives here as one method so both writes
    are guaranteed to happen in the caller's existing transaction, in
    the order the partial unique index requires (old unset before new
    set — see models/agent_version.py's own docstring)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        agent_id: uuid.UUID,
        label: str,
        adapter_type: str,
        adapter_config: dict[str, Any],
        observability_level: int,
    ) -> AgentVersion:
        version = AgentVersion(
            agent_id=agent_id,
            label=label,
            adapter_type=adapter_type,
            adapter_config=adapter_config,
            observability_level=observability_level,
        )
        self._session.add(version)
        await self._session.flush()
        await self._session.refresh(version)
        return version

    async def list_by_agent(self, agent_id: uuid.UUID) -> list[AgentVersion]:
        result = await self._session.execute(
            select(AgentVersion)
            .where(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.created_at)
        )
        return list(result.scalars().all())

    async def get_by_id(self, version_id: uuid.UUID) -> AgentVersion | None:
        result = await self._session.execute(
            select(AgentVersion).where(AgentVersion.id == version_id)
        )
        return result.scalar_one_or_none()

    async def get_by_agent_and_label(self, agent_id: uuid.UUID, label: str) -> AgentVersion | None:
        result = await self._session.execute(
            select(AgentVersion).where(
                AgentVersion.agent_id == agent_id, AgentVersion.label == label
            )
        )
        return result.scalar_one_or_none()

    async def get_baseline(self, agent_id: uuid.UUID) -> AgentVersion | None:
        result = await self._session.execute(
            select(AgentVersion).where(
                AgentVersion.agent_id == agent_id, AgentVersion.is_baseline.is_(True)
            )
        )
        return result.scalar_one_or_none()

    async def promote_baseline(self, *, agent_id: uuid.UUID, target: AgentVersion) -> AgentVersion:
        """Unsets the agent's current baseline (if any and if it isn't
        already `target`), then sets `target` — always in that order,
        within the caller's existing transaction, so the partial unique
        index (`ix_agent_versions_one_baseline_per_agent`) never
        observes two baseline rows for the same agent at once."""
        current = await self.get_baseline(agent_id)
        if current is not None and current.id != target.id:
            current.is_baseline = False
            self._session.add(current)
            await self._session.flush()

        if not target.is_baseline:
            target.is_baseline = True
            self._session.add(target)
            await self._session.flush()

        await self._session.refresh(target)
        return target
