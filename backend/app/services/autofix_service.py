"""Phase 19 — AutoFix orchestration.

    TestCaseResult (FAIL/INCONCLUSIVE) -> Phase 18 RCA evidence (reused,
    not recomputed) -> app.autofix.proposal.build_autofix_proposal()
    (pure, deterministic, whitelist-only) -> either:
      - Option 4 (owner_suggestion): TestCaseResult.suggested_fix is
        written directly, prefixed "[NOT APPLIED]" — no approval, since
        nothing about the evaluated evidence changes.
      - Options 1-3: a real `Approval(suite_run_id=..., node="auto_fix")`
        row is created via the SAME Approval model/table/repository
        Phase 18 already uses for Release Gate approvals — not a second
        approval system. The proposal's structured details (action,
        field, current/proposed value) are round-tripped as JSON text in
        `Approval.reason`, the same field the legacy Run workflow already
        uses to describe a pending auto_fix/release_decision request.

Applying an approved proposal (`apply_and_reverify()`) is invoked ONLY
from app/services/approval_service.py's `_decide_suite_run_approval()`,
and ONLY when the approval is actually being APPROVED — a rejected or
still-pending approval is never applied (§ "unapproved fix cannot be
applied"). It re-validates the field name against the exact same
whitelist app/autofix/proposal.py drew it from (app/autofix/apply.py),
applies the change via the EXISTING TestSuiteService.patch_case() /
AgentService.update_agent() — never a raw SQL write, never a JSON patch,
never touching AgentVersion.adapter_config (that model/column is not
imported anywhere in this module) — then re-verifies by executing a
fresh SuiteRun of the same TestSuite/AgentVersion through the EXISTING,
unmodified Suite Runner (app/services/suite_runner.execute_suite_run),
and records whether the specific affected TestCase now resolves.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.autofix.apply import bound_trial_count, validate_agent_field, validate_testcase_field
from app.autofix.proposal import build_autofix_proposal
from app.core.exceptions import NotFoundError, ValidationError
from app.models.approval import Approval
from app.repositories.approval_repository import ApprovalRepository
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_case_result_repository import TestCaseResultRepository
from app.schemas.autofix import AutoFixProposalRead
from app.services.activity_service import ActivityService
from app.services.agent_service import AgentService
from app.services.suite_run_service import SuiteRunService
from app.services.suite_runner import execute_suite_run
from app.services.test_suite_service import TestSuiteService

_NOT_APPLIED_PREFIX = "[NOT APPLIED] "


class AutoFixService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._suite_runs = SuiteRunService(session)
        self._suites = TestSuiteService(session)
        self._agents = AgentService(session)
        self._cases = TestCaseRepository(session)
        self._results = TestCaseResultRepository(session)
        self._approvals = ApprovalRepository(session)
        self._activity = ActivityService(session)

    async def propose(
        self,
        *,
        suite_run_id: uuid.UUID,
        result_id: uuid.UUID,
        owner_id: uuid.UUID,
        prefer_agent_default: bool = False,
    ) -> AutoFixProposalRead:
        # Ownership chain reused verbatim: SuiteRun -> TestSuite -> Agent
        # -> Project (SuiteRunService.get_result()/get_suite_run(), Phase
        # 14, unmodified).
        result = await self._suite_runs.get_result(
            suite_run_id=suite_run_id, result_id=result_id, owner_id=owner_id
        )
        test_case = await self._cases.get_by_id(result.test_case_id)
        if test_case is None:
            raise NotFoundError(f"Test case not found: {result.test_case_id}")
        suite_run = await self._suite_runs.get_suite_run(
            suite_run_id=suite_run_id, owner_id=owner_id
        )
        suite = await self._suites.get_suite(suite_id=suite_run.suite_id, owner_id=owner_id)
        agent = await self._agents.get_agent(agent_id=suite.agent_id, owner_id=owner_id)

        proposal = build_autofix_proposal(
            test_case, result, agent=agent, prefer_agent_default=prefer_agent_default
        )

        if proposal.option == "owner_suggestion":
            await self._results.set_suggested_fix(result, _NOT_APPLIED_PREFIX + proposal.rationale)
            await self._session.commit()
            await self._activity.record(
                owner_id=owner_id,
                event_type="autofix_proposed",
                title="AutoFix Proposed",
                description=proposal.rationale,
                entity_type="test_case_result",
                entity_id=result.id,
                metadata={"option": proposal.option, "rca_category": proposal.rca_category},
            )
            return AutoFixProposalRead(
                option=proposal.option,
                rca_category=proposal.rca_category,
                field=proposal.field,
                current_value=proposal.current_value,
                proposed_value=proposal.proposed_value,
                rationale=proposal.rationale,
                requires_approval=False,
                approval_id=None,
                suggested_fix_recorded=True,
            )

        payload = {
            "autofix": True,
            "action": proposal.option,
            "test_case_id": str(test_case.id),
            "test_case_result_id": str(result.id),
            "suite_run_id": str(suite_run_id),
            "suite_id": str(suite.id),
            "agent_id": str(suite.agent_id),
            "agent_version_id": str(suite_run.agent_version_id),
            "rca_category": proposal.rca_category,
            "field": proposal.field,
            "current_value": proposal.current_value,
            "proposed_value": proposal.proposed_value,
            "rationale": proposal.rationale,
        }
        approval = await self._approvals.create(
            suite_run_id=suite_run_id, node="auto_fix", reason=json.dumps(payload)
        )
        await self._session.commit()
        await self._activity.record(
            owner_id=owner_id,
            event_type="autofix_proposed",
            title="AutoFix Proposed",
            description=proposal.rationale,
            entity_type="test_case_result",
            entity_id=result.id,
            metadata={"option": proposal.option, "approval_id": str(approval.id)},
        )
        return AutoFixProposalRead(
            option=proposal.option,
            rca_category=proposal.rca_category,
            field=proposal.field,
            current_value=proposal.current_value,
            proposed_value=proposal.proposed_value,
            rationale=proposal.rationale,
            requires_approval=True,
            approval_id=approval.id,
            suggested_fix_recorded=False,
        )

    async def apply_and_reverify(
        self, approval: Approval, *, owner_id: uuid.UUID
    ) -> dict[str, Any]:
        """Applies exactly the one whitelisted change an approved
        `node="auto_fix"` Approval described, then re-verifies via a
        fresh SuiteRun. Raises ValidationError (never silently no-ops)
        if the payload's field/action is not on the explicit whitelist —
        an approval whose apply step fails is left exactly as it was
        about to be marked (the caller, app/services/approval_service.py,
        calls this BEFORE mark_decided(), so a raised error here means
        the approval never actually gets marked "approved")."""
        payload = json.loads(approval.reason or "{}")
        action = payload.get("action")
        test_case_id = uuid.UUID(payload["test_case_id"])
        suite_id = uuid.UUID(payload["suite_id"])
        agent_id = uuid.UUID(payload["agent_id"])
        agent_version_id = uuid.UUID(payload["agent_version_id"])

        if action == "testcase_edit":
            field = payload["field"]
            validate_testcase_field(field)
            await self._suites.patch_case(
                case_id=test_case_id,
                owner_id=owner_id,
                payload={field: payload["proposed_value"]},
                fields_set={field},
            )
        elif action == "agent_default_edit":
            field = payload["field"]
            validate_agent_field(field)
            await AgentService(self._session).update_agent(
                agent_id=agent_id,
                owner_id=owner_id,
                payload={field: payload["proposed_value"]},
                fields_set={field},
            )
        elif action == "trial_count_increase":
            new_count = bound_trial_count(payload["proposed_value"])
            await self._suites.patch_case(
                case_id=test_case_id,
                owner_id=owner_id,
                payload={"trial_count": new_count},
                fields_set={"trial_count"},
            )
        else:
            raise ValidationError(f"unknown AutoFix action: {action!r}")

        # Re-verification: a fresh SuiteRun of the same TestSuite/
        # AgentVersion, through the existing, unmodified Suite Runner —
        # never a bespoke single-case execution path.
        new_suite_run = await self._suite_runs.create_suite_run(
            suite_id=suite_id,
            owner_id=owner_id,
            agent_version_id=agent_version_id,
            max_concurrency=1,
        )
        await execute_suite_run(new_suite_run.id)

        new_results = await self._results.list_by_suite_run(new_suite_run.id)
        new_result = next((r for r in new_results if r.test_case_id == test_case_id), None)

        return {
            "suite_run_id": str(new_suite_run.id),
            "new_verdict": new_result.verdict if new_result is not None else None,
            "resolved": bool(new_result is not None and new_result.verdict == "PASS"),
        }
