from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.agent_version import AgentVersion
    from app.models.project import Project


class Agent(UUIDMixin, TimestampMixin, Base):
    """Phase 11: a registered System Under Test (SUT) — the real external
    or local agent a user connects to AgentOps, owned by a Project.

    Per the locked architecture audit (Final Architecture Spec §7-§8):
    this row is the identity + default-evaluation-contract half of the
    registry; concrete connection details and the observability level
    actually tested live on AgentVersion (below), one-to-many, so a
    SuiteRun can always point at an immutable configuration snapshot.

    default_* fields are the Evaluation Contract's defaults (§8 of the
    locked audit: "not a separate entity... fields live as defaults on
    Agent and overridable per TestCase" — TestCase does not exist yet;
    these columns are added now, ahead of Phase 12, because they belong
    to Agent's own schema, not to a future table).
    """

    __tablename__ = "agents"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    default_expected_behavior: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )
    default_forbidden_behavior: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )
    default_output_schema: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    default_latency_threshold_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    default_allowed_tools: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    default_required_tools: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)

    min_call_interval_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    default_timeout_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="30000"
    )

    project: Mapped[Project] = relationship("Project")
    versions: Mapped[list[AgentVersion]] = relationship(
        "AgentVersion",
        back_populates="agent",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentVersion.created_at",
    )
