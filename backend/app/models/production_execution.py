from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.agent_version import AgentVersion


class ProductionExecution(UUIDMixin, Base):
    """Phase 20: one piece of post-release execution evidence, ingested
    from an already-released/external agent run — NOT executed by
    AgentOps itself (see app/services/production_execution_service.py's
    own docstring: this table only ever records evidence someone else's
    execution already produced).

    `(agent_version_id, external_execution_id)` is unique — the locked
    idempotency requirement (§3): repeated ingestion of the same
    external execution must never create a second row. `agent_version_id`
    -> RESTRICT, not CASCADE, for the same reproducibility reason
    SuiteRun.agent_version_id already uses (models/suite_run.py): a
    historical execution record must never be silently orphaned by
    deleting the version it was evaluated against.

    No `updated_at` — like SuiteRun/AgentVersion, this row is immutable
    once ingested and evaluated; nothing in this phase ever mutates one
    after creation.

    `checks`/`verdict` are computed exactly once at ingestion time by
    reusing Phase 13's evaluate() + Phase 15's Safety/Grounding
    (app/evaluation/production.py) — never a second evaluator.
    """

    __tablename__ = "production_executions"
    __table_args__ = (
        UniqueConstraint(
            "agent_version_id",
            "external_execution_id",
            name="uq_production_executions_agent_version_id_external_execution_id",
        ),
        CheckConstraint(
            "verdict IN ('PASS', 'FAIL', 'INCONCLUSIVE')",
            name="ck_production_executions_verdict",
        ),
    )

    agent_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    external_execution_id: Mapped[str] = mapped_column(String(255), nullable=False)

    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actual_output: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    trace: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    # The ORM attribute is named `execution_metadata` for the same reason
    # TestCase.case_metadata is (models/test_case.py's own docstring) —
    # `metadata` is reserved on a SQLAlchemy declarative model.
    execution_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, server_default="{}"
    )

    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    checks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    agent_version: Mapped[AgentVersion] = relationship("AgentVersion")
