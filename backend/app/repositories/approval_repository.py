from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.approval import Approval
from app.models.project import Project
from app.models.run import Run
from app.models.suite_run import SuiteRun
from app.models.test_suite import TestSuite


class ApprovalRepository:
    """Database access for the approvals queue. No ownership rules, no
    HTTP concerns — list_for_owner()'s join is the one exception, since
    "which approvals can this user see" is inherent to what the query
    selects, not a separate business rule layered on top (same reasoning
    as ProjectRepository's owner-scoped queries elsewhere in this app)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        run_id: uuid.UUID | None = None,
        suite_run_id: uuid.UUID | None = None,
        node: str,
        reason: str | None,
    ) -> Approval:
        # Phase 18: exactly one of run_id/suite_run_id — the same DB
        # CHECK constraint enforces this; this ValueError catches a
        # programming error at the call site before it ever reaches SQL.
        if (run_id is None) == (suite_run_id is None):
            raise ValueError("exactly one of run_id or suite_run_id must be given")
        approval = Approval(
            run_id=run_id, suite_run_id=suite_run_id, node=node, status="pending", reason=reason
        )
        self._session.add(approval)
        await self._session.flush()
        # No session.refresh(approval) — same reasoning as
        # FlagRepository.bulk_create()/ToolCallRepository.bulk_create():
        # nothing here reads back a server-generated default (requested_at)
        # through this method's return value, so the extra round trip
        # isn't needed. (The real persistence bug this project found via
        # live testing was elsewhere — see app/approvals/service.py's
        # get_snapshot() — not related to refresh() at all.)
        return approval

    async def get_pending_for_suite_run(self, suite_run_id: uuid.UUID) -> Approval | None:
        """Phase 18: idempotency for Release Gate approval creation —
        calling the release endpoint again while a "release_decision"
        approval is still pending must return the existing request, not
        queue a second one, matching app/approvals/service.py's own
        start_release_review() idempotency for the legacy Run workflow."""
        result = await self._session.execute(
            select(Approval).where(
                Approval.suite_run_id == suite_run_id, Approval.status == "pending"
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, approval_id: uuid.UUID) -> Approval | None:
        result = await self._session.execute(select(Approval).where(Approval.id == approval_id))
        return result.scalar_one_or_none()

    async def get_owner_id(self, approval: Approval) -> uuid.UUID | None:
        """Resolves the project owner for `approval`'s run — used for the
        ownership check before a decide() call, mirroring how every other
        endpoint in this app verifies ownership before mutating anything."""
        result = await self._session.execute(
            select(Project.owner_id)
            .join(Run, Run.project_id == Project.id)
            .where(Run.id == approval.run_id)
        )
        return result.scalar_one_or_none()

    async def list_for_owner(
        self, owner_id: uuid.UUID, *, status: str | None = None, limit: int = 100
    ) -> list[Approval]:
        query = (
            select(Approval)
            .join(Run, Run.id == Approval.run_id)
            .join(Project, Project.id == Run.project_id)
            .where(Project.owner_id == owner_id)
            .order_by(Approval.requested_at.desc())
            .limit(limit)
        )
        if status is not None:
            query = query.where(Approval.status == status)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def list_for_owner_suite_run(
        self, owner_id: uuid.UUID, *, status: str | None = None, limit: int = 100
    ) -> list[Approval]:
        """Phase 18 correction: the SuiteRun-scoped sibling of
        list_for_owner() above — same "the join IS the ownership rule"
        reasoning, over the SuiteRun -> TestSuite -> Agent -> Project
        chain instead of Run -> Project. list_for_owner() itself is
        untouched; app/services/approval_service.py's list_approvals()
        combines both so GET /approvals shows a user's approvals of
        either kind through the one existing endpoint."""
        query = (
            select(Approval)
            .join(SuiteRun, SuiteRun.id == Approval.suite_run_id)
            .join(TestSuite, TestSuite.id == SuiteRun.suite_id)
            .join(Agent, Agent.id == TestSuite.agent_id)
            .join(Project, Project.id == Agent.project_id)
            .where(Project.owner_id == owner_id)
            .order_by(Approval.requested_at.desc())
            .limit(limit)
        )
        if status is not None:
            query = query.where(Approval.status == status)
        result = await self._session.execute(query)
        return list(result.scalars().all())

    async def mark_decided(
        self, approval: Approval, *, status: str, decided_by: uuid.UUID, reason: str | None
    ) -> Approval:
        approval.status = status
        approval.decided_by = decided_by
        approval.decided_at = datetime.now(UTC)
        if reason is not None:
            approval.reason = reason
        await self._session.flush()
        # No session.refresh(approval) — see create()'s comment above.
        return approval
