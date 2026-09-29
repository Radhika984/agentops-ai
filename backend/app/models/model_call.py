from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.run import Run


class ModelCall(UUIDMixin, TimestampMixin, Base):
    """Phase 8: an audit-log row for one LLM call routed through
    app/ai/router.py, per the blueprint's schema (agent, model, tokens_in,
    tokens_out, cost, cache_hit, created_at).

    `run_id` is a deliberate addition beyond the blueprint's minimum
    schema (nullable — not every call happens inside a run; the /ask
    endpoint calls the model too, with no run to attribute it to). It's
    what lets agents/cost_optimization.py correlate a model/agent's calls
    with whether the run they belonged to actually succeeded, which is
    the only real outcome signal this project captures — there's no
    separate labeled-accuracy dataset per the blueprint's own DB schema.
    ON DELETE SET NULL, not CASCADE: a model_calls row is a cost/billing
    record, not run-scoped audit data (unlike ToolCall/Flag) — it should
    outlive the run it happened to be part of.

    `owner_id` (nullable, same ON DELETE SET NULL reasoning as run_id)
    is what GET /api/v1/cost actually scopes on — added because run_id
    alone cannot: it only ever links the legacy Run graph's calls back
    to an owner via Project, while every modern call site (the Suite
    Runner's rubric-judge/grounding checks, on-demand RCA hypothesis,
    safety's LLM fallback) has no Run at all. Populated at write time
    from app/ai/client.py's current_owner_id contextvar, set by whichever
    already-ownership-checked service is about to trigger a model call
    (see run_service.py, suite_runner.py, rca_service.py, ask_service.py,
    production_execution_service.py) — never guessed or backfilled.

    `cost` is Numeric(10, 6), not float: costs here are tiny
    fractional-cent amounts (see ai/router.py's docstring on where this
    number comes from) where float's binary rounding would visibly drift
    over many rows summed on the cost dashboard.
    """

    __tablename__ = "model_calls"

    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    agent: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    model_group: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[float] = mapped_column(Numeric(10, 6, asdecimal=False), nullable=False)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    run: Mapped[Run | None] = relationship("Run")
