from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.production_execution import ProductionExecution


class ProductionExecutionRepository:
    """Database access for post-release execution evidence. No ownership
    rules, no evaluation logic (that's app/evaluation/production.py), no
    HTTP concerns — matches app/repositories/test_case_result_repository.py's
    own convention."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_agent_version_and_external_id(
        self, *, agent_version_id: uuid.UUID, external_execution_id: str
    ) -> ProductionExecution | None:
        """Phase 20 (§3): the idempotency check — called BEFORE create()
        so a repeated ingestion of the same external execution returns
        the already-persisted row rather than raising a unique
        -constraint violation or creating a duplicate."""
        result = await self._session.execute(
            select(ProductionExecution).where(
                ProductionExecution.agent_version_id == agent_version_id,
                ProductionExecution.external_execution_id == external_execution_id,
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self, *, agent_version_id: uuid.UUID, external_execution_id: str, **fields: Any
    ) -> ProductionExecution:
        execution = ProductionExecution(
            agent_version_id=agent_version_id,
            external_execution_id=external_execution_id,
            **fields,
        )
        self._session.add(execution)
        await self._session.flush()
        await self._session.refresh(execution)
        return execution

    async def get_by_id(self, execution_id: uuid.UUID) -> ProductionExecution | None:
        result = await self._session.execute(
            select(ProductionExecution).where(ProductionExecution.id == execution_id)
        )
        return result.scalar_one_or_none()

    async def list_by_agent_version(
        self, agent_version_id: uuid.UUID, *, limit: int = 100
    ) -> list[ProductionExecution]:
        result = await self._session.execute(
            select(ProductionExecution)
            .where(ProductionExecution.agent_version_id == agent_version_id)
            .order_by(ProductionExecution.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())
