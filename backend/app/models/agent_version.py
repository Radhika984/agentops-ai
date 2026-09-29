from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from app.models.agent import Agent


class AgentVersion(UUIDMixin, Base):
    """Phase 11: one immutable connection-configuration snapshot for an
    Agent. Per the locked audit (§7): "a SuiteRun must remain
    reproducible — re-reading a historical SuiteRun must show exactly
    what config produced those results... adapter_config is therefore
    write-once — a config change creates a new AgentVersion." There is
    deliberately no updated_at and no update endpoint for adapter_type/
    adapter_config/observability_level/label: immutability is enforced
    structurally, by never exposing a way to change them, not by a
    runtime check on an update path that doesn't exist.

    is_baseline is the one field this row's identity does NOT cover —
    promoting a version (app/services/agent_service.py) flips it on this
    row and off the agent's previous baseline, atomically, in the same
    transaction; it is bookkeeping about *which* version is the current
    comparison target (§18 of the locked audit — Versioning &
    Regression), not part of what was tested.
    """

    __tablename__ = "agent_versions"
    __table_args__ = (
        UniqueConstraint("agent_id", "label", name="uq_agent_versions_agent_id_label"),
        CheckConstraint(
            "adapter_type IN ('http', 'local')", name="ck_agent_versions_adapter_type"
        ),
        CheckConstraint(
            "observability_level BETWEEN 1 AND 4",
            name="ck_agent_versions_observability_level",
        ),
        # Exactly one baseline version per agent, enforced by the
        # database itself — a partial unique index, not merely an
        # application-layer convention (see the locked audit §7/§23).
        Index(
            "ix_agent_versions_one_baseline_per_agent",
            "agent_id",
            unique=True,
            postgresql_where=text("is_baseline"),
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    adapter_type: Mapped[str] = mapped_column(String(20), nullable=False)
    adapter_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    observability_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_baseline: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    agent: Mapped[Agent] = relationship("Agent", back_populates="versions")
