"""Phase 12 — Evaluation Contract + Test Cases.

Stores and validates the ground-truth layer the locked audit's
Evaluation Engine (Phase 13+) will read from. This module deliberately
implements NO evaluation logic: no PASS/FAIL, no assertion execution, no
tool-trajectory comparison, no safety/grounding/LLM-judge evaluation, no
suite execution. It only persists a TestSuite/TestCase and enforces the
one cross-field domain rule the locked audit requires at this layer —
that a TestCase is never allowed to exist with zero ground-truth
mechanisms (§9: "A test case with no meaningful correctness source must
NOT be represented as a normal successful evaluation" — the concrete
mechanism for that, this early, is refusing to let one be created or
edited into that state at all).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidStateError, NotFoundError, ValidationError
from app.models.test_case import TestCase
from app.models.test_suite import TestSuite
from app.repositories.test_case_repository import TestCaseRepository
from app.repositories.test_suite_repository import TestSuiteRepository
from app.services.agent_service import AgentService

# The locked audit's ground-truth mechanisms (§9), extended to include
# output_schema — it is a real, independently-executed Phase 13
# evaluation check (app/evaluation/checks/output_schema.py) exactly like
# the other five, so a TestCase carrying only a schema is not actually
# "no meaningful correctness source". A case is valid if at least one is
# *present* — meaningfully, not just non-null: an empty list/empty
# string/empty dict must not count, or an API caller could satisfy the
# rule with `"assertions": []` (or `"output_schema": {}`) and still have
# nothing evaluable.
GROUND_TRUTH_FIELDS = (
    "expected_output",
    "assertions",
    "reference_context",
    "expected_tool_calls",
    "output_schema",
    "rubric",
)

# Schema field name -> ORM attribute name, for the one field whose name
# differs between the two layers (see models/test_case.py's docstring on
# why `metadata` can't be the ORM attribute name directly).
_SCHEMA_TO_MODEL_FIELD = {"metadata": "case_metadata"}


def _has_ground_truth(fields: dict[str, Any]) -> bool:
    return any(fields.get(name) for name in GROUND_TRUTH_FIELDS)


def _to_model_fields(schema_fields: dict[str, Any]) -> dict[str, Any]:
    return {_SCHEMA_TO_MODEL_FIELD.get(key, key): value for key, value in schema_fields.items()}


class TestSuiteService:
    """Ownership and business rules for TestSuite/TestCase. Raises
    framework-independent domain exceptions only — never FastAPI's
    HTTPException — matching AgentService's own convention exactly.

    Ownership is always resolved the same way: TestSuite belongs to an
    Agent (verified via a real AgentService instance, not a
    reimplementation of its ownership chain), TestCase belongs to a
    TestSuite that belongs to an Agent that belongs to a Project.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._agents = AgentService(session)
        self._suites = TestSuiteRepository(session)
        self._cases = TestCaseRepository(session)

    # ---- TestSuite -----------------------------------------------------

    async def create_suite(
        self, *, agent_id: uuid.UUID, owner_id: uuid.UUID, name: str
    ) -> TestSuite:
        # Raises NotFoundError / PermissionDeniedError if the agent
        # doesn't exist or its project isn't owned by owner_id.
        await self._agents.get_agent(agent_id=agent_id, owner_id=owner_id)

        suite = await self._suites.create(agent_id=agent_id, name=name)
        await self._session.commit()
        return suite

    async def list_suites(self, *, agent_id: uuid.UUID, owner_id: uuid.UUID) -> list[TestSuite]:
        await self._agents.get_agent(agent_id=agent_id, owner_id=owner_id)
        return await self._suites.list_by_agent(agent_id)

    async def list_all_for_owner(self, *, owner_id: uuid.UUID) -> list[TestSuite]:
        """The account-wide "Test Suites" nav page — no per-agent scoping,
        just every TestSuite this owner can see (the join IS the
        ownership rule; see TestSuiteRepository.list_for_owner())."""
        return await self._suites.list_for_owner(owner_id)

    async def get_suite(self, *, suite_id: uuid.UUID, owner_id: uuid.UUID) -> TestSuite:
        """Public ownership-checked lookup — used by other services
        (e.g. app/services/suite_run_service.py, Phase 14) that need a
        TestSuite without going through this module's own CRUD routes."""
        return await self._get_owned_suite(suite_id=suite_id, owner_id=owner_id)

    async def _get_owned_suite(self, *, suite_id: uuid.UUID, owner_id: uuid.UUID) -> TestSuite:
        suite = await self._suites.get_by_id(suite_id)
        if suite is None:
            raise NotFoundError(f"Test suite not found: {suite_id}")
        # Raises NotFoundError / PermissionDeniedError exactly as
        # AgentService already does for every resource that hangs off
        # an agent.
        await self._agents.get_agent(agent_id=suite.agent_id, owner_id=owner_id)
        return suite

    # ---- TestCase ------------------------------------------------------

    async def create_case(
        self, *, suite_id: uuid.UUID, owner_id: uuid.UUID, fields: dict[str, Any]
    ) -> TestCase:
        suite = await self._get_owned_suite(suite_id=suite_id, owner_id=owner_id)

        if not _has_ground_truth(fields):
            raise ValidationError(
                "A test case requires at least one of: " + ", ".join(GROUND_TRUTH_FIELDS)
            )

        case = await self._cases.create(suite_id=suite.id, fields=_to_model_fields(fields))
        await self._session.commit()
        return case

    async def list_cases(self, *, suite_id: uuid.UUID, owner_id: uuid.UUID) -> list[TestCase]:
        await self._get_owned_suite(suite_id=suite_id, owner_id=owner_id)
        return await self._cases.list_by_suite(suite_id)

    async def _get_owned_case(self, *, case_id: uuid.UUID, owner_id: uuid.UUID) -> TestCase:
        case = await self._cases.get_by_id(case_id)
        if case is None:
            raise NotFoundError(f"Test case not found: {case_id}")
        await self._get_owned_suite(suite_id=case.suite_id, owner_id=owner_id)
        return case

    async def patch_case(
        self,
        *,
        case_id: uuid.UUID,
        owner_id: uuid.UUID,
        payload: dict[str, Any],
        fields_set: set[str],
    ) -> TestCase:
        case = await self._get_owned_case(case_id=case_id, owner_id=owner_id)

        updates = {key: payload[key] for key in fields_set if key in payload}

        # Revalidate the *complete resulting* case's ground-truth
        # requirement — current values for any ground-truth field the
        # patch didn't touch, overridden by whatever the patch actually
        # sets (including explicitly clearing one to null/empty). A
        # patch that would leave the case with zero ground-truth
        # mechanisms is rejected before anything is written.
        resulting = {name: getattr(case, name) for name in GROUND_TRUTH_FIELDS}
        resulting.update({k: v for k, v in updates.items() if k in GROUND_TRUTH_FIELDS})
        if not _has_ground_truth(resulting):
            raise ValidationError(
                "This update would leave the test case with no ground-truth mechanism — "
                "at least one of: " + ", ".join(GROUND_TRUTH_FIELDS) + " must remain set."
            )

        if updates:
            case = await self._cases.update(case, **_to_model_fields(updates))
            await self._session.commit()

        return case

    async def delete_case(self, *, case_id: uuid.UUID, owner_id: uuid.UUID) -> None:
        case = await self._get_owned_case(case_id=case_id, owner_id=owner_id)
        await self._cases.delete(case)
        await self._session.commit()

    # ---- Phase 20: regression candidates --------------------------------

    async def create_candidate_case(
        self,
        *,
        suite_id: uuid.UUID,
        owner_id: uuid.UUID,
        fields: dict[str, Any],
        source_execution_id: uuid.UUID,
    ) -> TestCase:
        """The only other path (besides create_case()) that persists a
        new TestCase — reuses the exact same ground-truth validation
        (_has_ground_truth()) and field mapping, just with
        status="candidate" and source_execution_id set so
        TestCaseRepository.list_active_by_suite() (used by the Suite
        Runner) excludes it until a human calls accept_candidate()
        below. A candidate is proposed FROM a real ProductionExecution
        (app/services/production_execution_service.py) but is never
        itself capable of touching Agent/AgentVersion/credentials — it
        is a plain TestCase row, created through the exact same
        whitelisted field set create_case() already uses."""
        suite = await self._get_owned_suite(suite_id=suite_id, owner_id=owner_id)

        if not _has_ground_truth(fields):
            raise ValidationError(
                "A regression candidate requires at least one of: " + ", ".join(GROUND_TRUTH_FIELDS)
            )

        model_fields = _to_model_fields(fields)
        model_fields["status"] = "candidate"
        model_fields["source_execution_id"] = source_execution_id
        case = await self._cases.create(suite_id=suite.id, fields=model_fields)
        await self._session.commit()
        return case

    async def accept_candidate(self, *, case_id: uuid.UUID, owner_id: uuid.UUID) -> TestCase:
        """The human-control step (§8): a candidate TestCase only starts
        being included in Suite Runner executions after this is called.
        Never a silent no-op — an already-active case raises
        InvalidStateError rather than masking a caller's mistaken
        assumption that it was still pending."""
        case = await self._get_owned_case(case_id=case_id, owner_id=owner_id)
        if case.status != "candidate":
            raise InvalidStateError(f"Test case {case_id} is not a pending candidate.")
        case = await self._cases.update(case, status="active")
        await self._session.commit()
        return case
