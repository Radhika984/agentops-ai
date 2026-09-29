from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.execution import AgentExecution
from app.adapters.factory import build_adapter
from app.adapters.http_adapter import HTTPAdapterConfig
from app.adapters.local_adapter import LocalAdapterConfig
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.repositories.agent_repository import AgentRepository
from app.repositories.agent_version_repository import AgentVersionRepository
from app.services.activity_service import ActivityService
from app.services.project_service import ProjectService

_ADAPTER_CONFIG_SCHEMAS: dict[str, type[HTTPAdapterConfig] | type[LocalAdapterConfig]] = {
    "http": HTTPAdapterConfig,
    "local": LocalAdapterConfig,
}


def _validate_adapter_config(adapter_type: str, adapter_config: dict[str, Any]) -> None:
    """Reuses the exact Phase 10 config schemas (app/adapters/http_adapter.py,
    app/adapters/local_adapter.py) to validate shape at registration time —
    never a second, parallel definition of what a valid config looks
    like. A version with a malformed config is rejected before it is
    ever persisted, so it can never later fail confusingly at
    test-invoke time for a reason registration should have caught."""
    schema = _ADAPTER_CONFIG_SCHEMAS[adapter_type]
    try:
        schema.model_validate(adapter_config)
    except PydanticValidationError as exc:
        raise ValidationError(f"invalid {adapter_type} adapter config: {exc}") from exc


class AgentService:
    """Ownership and business rules for the Agent Registry (Phase 11).
    Raises framework-independent domain exceptions only — never
    FastAPI's HTTPException — matching ProjectService/AskService/
    RunService's own convention exactly.

    Ownership is always resolved the same two/three-hop way: Agent
    belongs to a Project (checked via a real ProjectService instance —
    not a re-implementation of its ownership rule), AgentVersion belongs
    to an Agent that belongs to a Project.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._agents = AgentRepository(session)
        self._versions = AgentVersionRepository(session)
        self._activity = ActivityService(session)

    # ---- Agent -----------------------------------------------------

    async def create_agent(
        self, *, project_id: uuid.UUID, owner_id: uuid.UUID, name: str, description: str | None
    ) -> Agent:
        # Raises NotFoundError / PermissionDeniedError if the project
        # doesn't exist or isn't owned by owner_id — checked before
        # creating anything, exactly like RunService.create_run().
        await self._projects.get_project(project_id=project_id, owner_id=owner_id)

        agent = await self._agents.create(project_id=project_id, name=name, description=description)
        await self._session.commit()
        return agent

    async def list_agents(self, *, project_id: uuid.UUID, owner_id: uuid.UUID) -> list[Agent]:
        await self._projects.get_project(project_id=project_id, owner_id=owner_id)
        return await self._agents.list_by_project(project_id)

    async def _get_owned_agent(self, *, agent_id: uuid.UUID, owner_id: uuid.UUID) -> Agent:
        agent = await self._agents.get_by_id(agent_id)
        if agent is None:
            raise NotFoundError(f"Agent not found: {agent_id}")
        # Raises NotFoundError / PermissionDeniedError exactly as
        # ProjectService already does for every other resource that
        # hangs off a project.
        await self._projects.get_project(project_id=agent.project_id, owner_id=owner_id)
        return agent

    async def get_agent(self, *, agent_id: uuid.UUID, owner_id: uuid.UUID) -> Agent:
        return await self._get_owned_agent(agent_id=agent_id, owner_id=owner_id)

    async def update_agent(
        self,
        *,
        agent_id: uuid.UUID,
        owner_id: uuid.UUID,
        payload: dict[str, Any],
        fields_set: set[str],
    ) -> Agent:
        agent = await self._get_owned_agent(agent_id=agent_id, owner_id=owner_id)

        updates = {key: payload[key] for key in fields_set if key in payload}
        if updates:
            agent = await self._agents.update(agent, **updates)
            await self._session.commit()

        return agent

    # ---- AgentVersion ------------------------------------------------

    async def create_version(
        self,
        *,
        agent_id: uuid.UUID,
        owner_id: uuid.UUID,
        label: str,
        adapter_type: str,
        adapter_config: dict[str, Any],
        observability_level: int,
    ) -> AgentVersion:
        agent = await self._get_owned_agent(agent_id=agent_id, owner_id=owner_id)

        _validate_adapter_config(adapter_type, adapter_config)

        existing = await self._versions.get_by_agent_and_label(agent.id, label)
        if existing is not None:
            raise ConflictError(
                f"Agent {agent.id} already has a version labeled '{label}'"
            )

        version = await self._versions.create(
            agent_id=agent.id,
            label=label,
            adapter_type=adapter_type,
            adapter_config=adapter_config,
            observability_level=observability_level,
        )
        await self._session.commit()
        await self._activity.record(
            owner_id=owner_id,
            event_type="agent_version_created",
            title=f"Agent Version Created — {agent.name} {label}",
            entity_type="agent_version",
            entity_id=version.id,
            metadata={"agent_id": str(agent.id), "label": label},
        )
        return version

    async def list_versions(
        self, *, agent_id: uuid.UUID, owner_id: uuid.UUID
    ) -> list[AgentVersion]:
        await self._get_owned_agent(agent_id=agent_id, owner_id=owner_id)
        return await self._versions.list_by_agent(agent_id)

    async def _get_owned_version(
        self, *, agent_id: uuid.UUID, version_id: uuid.UUID, owner_id: uuid.UUID
    ) -> AgentVersion:
        agent = await self._get_owned_agent(agent_id=agent_id, owner_id=owner_id)
        version = await self._versions.get_by_id(version_id)
        if version is None or version.agent_id != agent.id:
            raise NotFoundError(f"Agent version not found: {version_id}")
        return version

    async def get_version(
        self, *, agent_id: uuid.UUID, version_id: uuid.UUID, owner_id: uuid.UUID
    ) -> AgentVersion:
        return await self._get_owned_version(
            agent_id=agent_id, version_id=version_id, owner_id=owner_id
        )

    async def promote_baseline(
        self, *, agent_id: uuid.UUID, version_id: uuid.UUID, owner_id: uuid.UUID
    ) -> AgentVersion:
        version = await self._get_owned_version(
            agent_id=agent_id, version_id=version_id, owner_id=owner_id
        )
        # Both writes (unset previous, set new) happen inside this one
        # session/transaction — a single commit() makes the promotion
        # atomic: either both apply or neither does.
        version = await self._versions.promote_baseline(agent_id=agent_id, target=version)
        await self._session.commit()
        await self._activity.record(
            owner_id=owner_id,
            event_type="agent_version_promoted",
            title=f"Agent Version Promoted — {version.label}",
            description=f"{version.label} is now the baseline version.",
            entity_type="agent_version",
            entity_id=version.id,
            metadata={"agent_id": str(agent_id)},
        )
        return version

    # ---- test-invoke ---------------------------------------------------

    async def test_invoke(
        self,
        *,
        agent_id: uuid.UUID,
        version_id: uuid.UUID,
        owner_id: uuid.UUID,
        input: dict[str, Any],
    ) -> AgentExecution:
        """Loads a persisted AgentVersion and invokes it through the
        unchanged Phase 10 adapter layer — build_adapter() and
        AgentAdapter.invoke() are not reimplemented here. Deliberately
        does not persist anything: no TestCaseResult, no SuiteRun exist
        yet (Phase 12/14), and this endpoint must not invent a
        stand-in for either.
        """
        version = await self._get_owned_version(
            agent_id=agent_id, version_id=version_id, owner_id=owner_id
        )
        adapter = build_adapter(version.adapter_type, version.adapter_config)
        return await adapter.invoke(input)
