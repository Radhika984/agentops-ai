"""Approval queue + release-review orchestration.

Per the blueprint's folder structure ("approvals/service.py — create/
resolve approval requests, ties into the graph's interrupt/resume"): this
is where "pause" and "resume" actually live.

Not LangGraph's `interrupt_before` + a persistent checkpointer: that was
attempted first and verified directly against this project's own Postgres
via a real interrupt/resume round trip — but `AsyncPostgresSaver` raises
immediately on Windows ("Psycopg cannot use the 'ProactorEventLoop' to
run in async mode"), because psycopg's async mode requires a Selector
event loop, which conflicts with this project's existing dependency on
Windows' default Proactor loop for Phase 5's MCP subprocess-based tools
(SelectorEventLoop does not support subprocesses on Windows). Since this
project's test suite and local dev both run on Windows, that would have
either broken Phase 5's tools (if the loop policy were switched) or been
unusable for the very thing it exists to test (if left alone) — a real,
verified incompatibility, not a shortcut around unfamiliar technology.

Instead, "pause" is nothing more than an `Approval` row with
status="pending" plus a release-workflow snapshot (`ReleaseSnapshot`)
persisted into `runs.state["release"]` (the same JSONB top-level-merge
mechanism Phase 7 already uses for OTel `trace` — see
RunRepository.merge_state_extra()). "Resume" is a fresh, stateless call
into the next workflow step, driven entirely by what's already in
Postgres. This is inherently restart-safe — there is never an in-memory
suspended execution to lose, since nothing is running while "paused" —
which is a stronger guarantee against the blueprint's own "Common
Mistake" ("forgetting that an interrupted graph run must be resumable
after a server restart, not just mid-process") than a checkpointer would
give without extra care, not a weaker one.
"""

from __future__ import annotations

import uuid
from typing import Literal, TypedDict, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents import auto_fix, release_decision, root_cause_analysis
from app.agents.state import FlagRecord
from app.core.exceptions import InvalidStateError
from app.models.approval import Approval
from app.models.run import Run
from app.repositories.approval_repository import ApprovalRepository
from app.repositories.flag_repository import FlagRepository
from app.repositories.run_repository import RunRepository

ReleaseStatus = Literal[
    "analyzing_failure",
    "awaiting_auto_fix_approval",
    "awaiting_release_approval",
    "done",
]


class ReleaseSnapshot(TypedDict):
    status: ReleaseStatus
    root_cause: str | None
    root_cause_pattern: str | None
    auto_fix_proposed_task: str | None
    auto_fix_applied: bool
    hard_gate_passed: bool | None
    soft_score: float | None
    soft_score_components: dict[str, float]
    decision: Literal["ship", "hold", "rollback"] | None
    reason: str | None


def _initial_snapshot() -> ReleaseSnapshot:
    return ReleaseSnapshot(
        status="analyzing_failure",
        root_cause=None,
        root_cause_pattern=None,
        auto_fix_proposed_task=None,
        auto_fix_applied=False,
        hard_gate_passed=None,
        soft_score=None,
        soft_score_components={},
        decision=None,
        reason=None,
    )


async def _persist(run_repo: RunRepository, run: Run, snapshot: ReleaseSnapshot) -> None:
    await run_repo.merge_state_extra(run, key="release", value=dict(snapshot))


def get_snapshot(run: Run) -> ReleaseSnapshot | None:
    """Returns a *copy* of run.state["release"], never the dict object
    itself — a real bug found via live testing: every caller here goes
    on to mutate the returned snapshot in place (`snapshot["status"] =
    ...`) before persisting it back via merge_state_extra(). Since a plain
    dict.get() returns the *same* nested object `run.state["release"]`
    already points to, that in-place mutation was silently rewriting
    run.state's own "before" picture too — so by the time
    merge_state_extra() reassigned `run.state = {**run.state, ...}`,
    SQLAlchemy's change-tracking compared the new value against an
    "old" value that had (invisibly) already been mutated to match it,
    saw no real difference, and skipped the UPDATE entirely. No
    exception, no error — decide() would return the correct
    (in-memory-only) snapshot to the caller while the database silently
    kept the pre-decision state. A shallow copy is enough: nothing here
    ever mutates a *nested* value (soft_score_components etc.), only
    top-level keys.
    """
    raw = run.state.get("release")
    return cast(ReleaseSnapshot, dict(raw)) if raw is not None else None


async def start_release_review(session: AsyncSession, run: Run) -> ReleaseSnapshot:
    """Entry point: reviews an already-terminal run (status "succeeded"
    or "failed") for release. Idempotent — calling it again on a run
    that already has a release snapshot just returns the existing one
    rather than restarting the workflow.
    """
    if run.status not in ("succeeded", "failed"):
        raise InvalidStateError(
            f"Run {run.id} is not in a terminal state (status={run.status!r}); "
            "cannot start a release review yet."
        )

    existing = get_snapshot(run)
    if existing is not None:
        return existing

    run_repo = RunRepository(session)
    approvals_repo = ApprovalRepository(session)

    goal = str(run.state["goal"])
    plan = list(run.state["plan"])
    flags = list(run.state["flags"])
    tool_calls = list(run.state["tool_calls"])
    evaluations = list(run.state["evaluations"])
    retry_count = int(run.state["retry_count"])
    verification_passed = bool(run.state["verification_passed"])

    snapshot = _initial_snapshot()

    if verification_passed:
        result = release_decision.decide_release(
            flags=cast(list[FlagRecord], flags),
            evaluations=evaluations,
            retry_count=retry_count,
            auto_fix_applied=False,
        )
        snapshot["hard_gate_passed"] = result.hard_gate_passed
        snapshot["soft_score"] = result.soft_score.value
        snapshot["soft_score_components"] = result.soft_score.components
        snapshot["reason"] = result.reason

        if result.proposed_decision == "hold":
            snapshot["status"] = "done"
            snapshot["decision"] = "hold"
        else:
            snapshot["status"] = "awaiting_release_approval"
            await approvals_repo.create(
                run_id=run.id, node="release_decision", reason=result.reason
            )

        await _persist(run_repo, run, snapshot)
        await session.commit()
        return snapshot

    # verification failed -> Root Cause Analysis
    rca_result = await root_cause_analysis.analyze_failure(
        goal=goal,
        plan=plan,
        flags=cast(list[FlagRecord], flags),
        tool_calls=tool_calls,
    )
    snapshot["root_cause"] = rca_result.hypothesis
    snapshot["root_cause_pattern"] = rca_result.pattern

    if not rca_result.whitelisted:
        snapshot["status"] = "done"
        await _persist(run_repo, run, snapshot)
        await session.commit()
        return snapshot

    proposed_task = await auto_fix.propose_fix(goal=goal, plan=plan)
    snapshot["auto_fix_proposed_task"] = proposed_task
    snapshot["status"] = "awaiting_auto_fix_approval"
    await approvals_repo.create(
        run_id=run.id,
        node="auto_fix",
        reason=f"Whitelisted pattern '{rca_result.pattern}' — proposed fix: append task "
        f"'{proposed_task}'.",
    )

    await _persist(run_repo, run, snapshot)
    await session.commit()
    return snapshot


async def _continue_after_auto_fix(
    session: AsyncSession, run: Run, snapshot: ReleaseSnapshot, *, approved: bool
) -> ReleaseSnapshot:
    run_repo = RunRepository(session)
    approvals_repo = ApprovalRepository(session)
    flags_repo = FlagRepository(session)

    if not approved:
        snapshot["status"] = "done"
        snapshot["auto_fix_applied"] = False
        await _persist(run_repo, run, snapshot)
        await session.commit()
        return snapshot

    plan = list(run.state["plan"])
    proposed_task = snapshot["auto_fix_proposed_task"]
    assert proposed_task is not None  # only reachable via the auto_fix approval path

    reverify = await auto_fix.apply_and_reverify(plan=plan, additional_task=proposed_task)
    if reverify.flags:
        await flags_repo.bulk_create(run_id=run.id, records=reverify.flags)

    if not reverify.passed:
        snapshot["status"] = "done"
        snapshot["auto_fix_applied"] = False
        snapshot["reason"] = "Auto Fix applied but the re-verify still failed."
        await _persist(run_repo, run, snapshot)
        await session.commit()
        return snapshot

    snapshot["auto_fix_applied"] = True

    original_flags = cast(list[FlagRecord], list(run.state["flags"]))
    result = release_decision.decide_release(
        flags=[*original_flags, *reverify.flags],
        evaluations=list(run.state["evaluations"]),
        retry_count=int(run.state["retry_count"]),
        auto_fix_applied=True,
    )
    snapshot["hard_gate_passed"] = result.hard_gate_passed
    snapshot["soft_score"] = result.soft_score.value
    snapshot["soft_score_components"] = result.soft_score.components
    snapshot["reason"] = result.reason

    if result.proposed_decision == "hold":
        snapshot["status"] = "done"
        snapshot["decision"] = "hold"
    else:
        snapshot["status"] = "awaiting_release_approval"
        await approvals_repo.create(run_id=run.id, node="release_decision", reason=result.reason)

    await _persist(run_repo, run, snapshot)
    await session.commit()
    return snapshot


async def _continue_after_release_decision(
    session: AsyncSession, run: Run, snapshot: ReleaseSnapshot, *, approved: bool
) -> ReleaseSnapshot:
    run_repo = RunRepository(session)
    snapshot["status"] = "done"
    snapshot["decision"] = "ship" if approved else "rollback"
    await _persist(run_repo, run, snapshot)
    await session.commit()
    return snapshot


async def decide(
    session: AsyncSession,
    approval: Approval,
    *,
    approved: bool,
    reason: str | None,
    decided_by: uuid.UUID,
) -> ReleaseSnapshot:
    """Resolves a pending approval and continues the release-review
    workflow from there. Raises InvalidStateError if `approval` has
    already been decided — a decision can only ever be made once."""
    if approval.status != "pending":
        raise InvalidStateError(f"Approval {approval.id} has already been decided.")

    approvals_repo = ApprovalRepository(session)
    run_repo = RunRepository(session)

    # Phase 18: Approval.run_id is now nullable (a suite_run_id-scoped
    # approval has none — see app/models/approval.py) — this workflow is
    # exclusively the legacy Run release-review one, so a None run_id
    # here (a suite-run approval reaching this function) is simply "no
    # such Run," the same outcome a stale/bad id would already produce,
    # not a crash. Deciding a suite_run_id-scoped approval through this
    # function is intentionally out of Phase 18's scope (see the Phase
    # 18 verification report).
    run = await run_repo.get_by_id(approval.run_id) if approval.run_id is not None else None
    if run is None:
        raise InvalidStateError(f"Run {approval.run_id} for approval {approval.id} not found.")

    snapshot = get_snapshot(run)
    if snapshot is None:
        raise InvalidStateError(f"Run {run.id} has no release-review snapshot to resume.")

    await approvals_repo.mark_decided(
        approval,
        status="approved" if approved else "rejected",
        decided_by=decided_by,
        reason=reason,
    )

    if approval.node == "auto_fix":
        return await _continue_after_auto_fix(session, run, snapshot, approved=approved)
    if approval.node == "release_decision":
        return await _continue_after_release_decision(session, run, snapshot, approved=approved)

    raise InvalidStateError(f"Unknown approval node: {approval.node!r}")
