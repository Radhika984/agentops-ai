from __future__ import annotations

import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.approvals import service as approvals_service
from app.approvals.service import ReleaseSnapshot
from app.core.exceptions import InvalidStateError, NotFoundError, PermissionDeniedError
from app.models.approval import Approval
from app.repositories.approval_repository import ApprovalRepository
from app.repositories.run_repository import RunRepository
from app.services.activity_service import ActivityService
from app.services.autofix_service import AutoFixService
from app.services.project_service import ProjectService
from app.services.suite_run_service import SuiteRunService


class ApprovalService:
    """Ownership and business rules for the approval queue / release
    -review workflow. Raises framework-independent domain exceptions only
    — never FastAPI's HTTPException — matching RunService/AskService.
    The actual Run-only workflow logic (RCA -> Auto Fix -> Release
    Decision, pause/resume) lives in app/approvals/service.py, which has
    no ownership or HTTP concerns of its own, per the blueprint's own
    file listing — completely unchanged and unaffected by SuiteRun
    approvals (see decide_approval()'s own branch below).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._projects = ProjectService(session)
        self._runs = RunRepository(session)
        self._approvals = ApprovalRepository(session)
        self._suite_runs = SuiteRunService(session)
        self._activity = ActivityService(session)

    async def request_release(
        self, *, project_id: uuid.UUID, run_id: uuid.UUID, owner_id: uuid.UUID
    ) -> ReleaseSnapshot:
        await self._projects.get_project(project_id=project_id, owner_id=owner_id)

        run = await self._runs.get_by_id(run_id)
        if run is None or run.project_id != project_id:
            raise NotFoundError(f"Run not found: {run_id}")

        return await approvals_service.start_release_review(self._session, run)

    async def list_approvals(
        self, *, owner_id: uuid.UUID, status: str | None = None
    ) -> list[Approval]:
        # Phase 18 correction: a user's approvals of either kind, through
        # the one existing endpoint — list_for_owner() (Run-scoped) is
        # untouched; list_for_owner_suite_run() is the new, additive
        # sibling query for SuiteRun-scoped approvals.
        run_approvals = await self._approvals.list_for_owner(owner_id, status=status)
        suite_run_approvals = await self._approvals.list_for_owner_suite_run(
            owner_id, status=status
        )
        combined = [*run_approvals, *suite_run_approvals]
        combined.sort(key=lambda a: a.requested_at, reverse=True)
        return combined

    async def decide_approval(
        self, *, approval_id: uuid.UUID, owner_id: uuid.UUID, approved: bool, reason: str | None
    ) -> ReleaseSnapshot | Approval:
        approval = await self._approvals.get_by_id(approval_id)
        if approval is None:
            raise NotFoundError(f"Approval not found: {approval_id}")

        if approval.suite_run_id is not None:
            return await self._decide_suite_run_approval(
                approval, owner_id=owner_id, approved=approved, reason=reason
            )

        # Existing Run-scoped path — byte-for-byte unchanged.
        approval_owner_id = await self._approvals.get_owner_id(approval)
        if approval_owner_id is None or approval_owner_id != owner_id:
            raise PermissionDeniedError("You do not have access to this approval")

        return await approvals_service.decide(
            self._session, approval, approved=approved, reason=reason, decided_by=owner_id
        )

    async def _decide_suite_run_approval(
        self, approval: Approval, *, owner_id: uuid.UUID, approved: bool, reason: str | None
    ) -> Approval:
        """Phase 18 correction: the minimal correct continuation for a
        SuiteRun-scoped "release_decision" approval. Unlike the legacy
        Run workflow, there is no persisted multi-stage release-review
        snapshot to advance — Phase 18's Release Gate is computed fresh
        from persisted evidence on every request (see
        app/services/release_gate_service.py), so "deciding" this
        approval is exactly and only: verify ownership through the real
        SuiteRun ownership chain (never a Run join — this approval's own
        run_id is None, by construction), then mark it decided via the
        same, already-approval-type-agnostic mark_decided() the Run path
        uses. This never calls app/approvals/service.py's decide() (the
        legacy Run-only continuation function) at all.
        """
        assert approval.suite_run_id is not None  # narrows for mypy; guaranteed by the caller
        try:
            await self._suite_runs.get_suite_run(
                suite_run_id=approval.suite_run_id, owner_id=owner_id
            )
        except (NotFoundError, PermissionDeniedError) as exc:
            raise PermissionDeniedError("You do not have access to this approval") from exc

        if approval.status != "pending":
            raise InvalidStateError(f"Approval {approval.id} has already been decided.")

        final_reason = reason
        if approval.node == "auto_fix":
            # Phase 19: an AutoFix proposal's structured JSON payload
            # lives in `reason` (see app/services/autofix_service.py) —
            # the human's own decide-time reason is merged in as
            # "decision_reason" rather than overwriting the payload, so
            # the original proposal (and, once applied, its
            # re-verification outcome) stays inspectable afterward.
            # Applying only ever happens here, on APPROVAL, and only
            # after ownership/pending-status checks above have already
            # passed — a rejected or already-decided proposal is never
            # applied.
            payload = json.loads(approval.reason or "{}")
            payload["decision_reason"] = reason
            if approved:
                payload["reverification"] = await AutoFixService(self._session).apply_and_reverify(
                    approval, owner_id=owner_id
                )
            final_reason = json.dumps(payload)

        decided = await self._approvals.mark_decided(
            approval,
            status="approved" if approved else "rejected",
            decided_by=owner_id,
            reason=final_reason,
        )
        await self._session.commit()
        decision_word = "Approved" if approved else "Rejected"
        node_label = approval.node.replace("_", " ").title()
        await self._activity.record(
            owner_id=owner_id,
            event_type="approval_decided",
            title=f"{decision_word} — {node_label}",
            entity_type="approval",
            entity_id=approval.id,
            metadata={"node": approval.node, "approved": approved},
        )
        return decided
