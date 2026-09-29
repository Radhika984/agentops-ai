from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_call import ModelCall


class ModelCallRepository:
    """Database access for the model_calls cost/usage log. No ownership
    rules, no HTTP concerns."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        agent: str,
        model_group: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost: float,
        cache_hit: bool,
        run_id: uuid.UUID | None = None,
        owner_id: uuid.UUID | None = None,
    ) -> ModelCall:
        call = ModelCall(
            run_id=run_id,
            owner_id=owner_id,
            agent=agent,
            model_group=model_group,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost=cost,
            cache_hit=cache_hit,
        )
        self._session.add(call)
        await self._session.flush()
        return call

    async def list_recent(self, *, limit: int = 500) -> list[ModelCall]:
        result = await self._session.execute(
            select(ModelCall).order_by(ModelCall.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())
