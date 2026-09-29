"""Phase 9 approval-queue / release-review integration tests.

Runs are seeded directly via the ORM into known terminal states ("a
seeded, known failure", per the blueprint's own phrasing for this
phase's required integration test) rather than driven through the full
Planner->...->Verification graph — this project already covers that
graph exhaustively in tests/test_agents.py/test_runs.py; what Phase 9
needs tested is the NEW release-review workflow that starts from an
already-finished run.

call_model() is mocked at the same seams tests/test_root_cause_analysis.py
and tests/test_auto_fix.py use; call_tool() is mocked for Auto Fix's
re-verify step; memory_manager.recall()/remember() are mocked — no
network, no real model call, no real sandbox subprocess.

Auth: tokens are minted directly via app.core.security.create_access_token
for ORM-seeded users, matching this file's "seed known state via the ORM"
approach rather than registering through the auth API.

test_decide_persists_correctly_across_genuinely_separate_sessions is a
deliberate regression test for a real bug found via live Docker testing,
not via this file's own (HTTP, shared-session) tests above: the `client`
fixture's dependency override yields the *same* db_session object for
every request in a test, so every call above shares one session/identity
map — unlike production, where every request opens a brand new
AsyncSessionLocal() (see app/db/session.py's get_db()). That difference
completely masked a real bug in app/approvals/service.py's get_snapshot()
(returning the *same* dict object run.state["release"] already points
to, rather than a copy — every caller then mutated it in place before
persisting, which silently rewrote run.state's own "before" picture too,
so SQLAlchemy's change-tracking on the later `run.state = {...}`
reassignment saw no real difference and skipped the UPDATE — see that
function's docstring for the full explanation) that only manifested with
fresh, per-call sessions, which is exactly how the real app actually
runs. This test deliberately opens a separate engine/session per step,
matching tests/test_runs.py's own `_background_task_uses_test_database`
pattern for the same reason.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents import auto_fix as auto_fix_mod
from app.agents import root_cause_analysis as rca_mod
from app.agents.schemas import AutoFixPatch, RootCauseHypothesis
from app.approvals import service as approvals_service
from app.core.security import create_access_token
from app.models.project import Project
from app.models.run import Run
from app.models.user import User
from app.repositories.approval_repository import ApprovalRepository
from app.repositories.run_repository import RunRepository
from app.tools.registry import ToolCallResult
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.anyio


async def _fake_recall_empty(
    query: str, *, source_type: str | None = None, top_k: int = 3
) -> list[str]:
    return []


async def _fake_remember_noop(
    *, content: str, source_type: str, source_id: object | None = None
) -> None:
    return None


@pytest.fixture(autouse=True)
def _mock_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rca_mod.memory_manager, "recall", _fake_recall_empty)
    monkeypatch.setattr(rca_mod.memory_manager, "remember", _fake_remember_noop)


async def _seed_user_and_project(session: AsyncSession, email: str) -> tuple[User, Project]:
    user = User(email=email, hashed_password="not-a-real-hash")
    session.add(user)
    await session.flush()

    project = Project(name="Release Review Test Project", owner_id=user.id)
    session.add(project)
    await session.flush()

    return user, project


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _base_state(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {
        "goal": "Plan a small team lunch",
        "plan": ["only one task"],
        "artifacts": {},
        "evaluations": [{"score": 1.0, "passed": True}],
        "status": "failed",
        "retry_count": 2,
        "verification_passed": False,
        "tool_calls": [
            {
                "tool_name": "run_python",
                "input": {"code": "x"},
                "output": "FAIL\n",
                "duration_ms": 1,
                "ok": True,
            }
        ],
        "retrieved_memory": [],
        "flags": [],
    }
    state.update(overrides)
    return state


def _safety_flag() -> dict[str, object]:
    return {"agent": "safety", "type": "destructive_filesystem", "severity": "high", "details": "d"}


async def _seed_run(
    session: AsyncSession, project: Project, *, status: str, state: dict[str, object]
) -> Run:
    run = Run(project_id=project.id, goal=str(state["goal"]), status=status, state=state)
    session.add(run)
    await session.flush()
    await session.refresh(run)
    return run


# ---- the required blueprint integration test: full failure -> RCA ->
# Auto Fix -> re-verify -> Release Decision -> Ship, with two real
# approval pause/resume round trips ----


async def test_full_failure_rca_autofix_reverify_release_loop(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, project = await _seed_user_and_project(db_session, "release-flow@example.com")
    run = await _seed_run(db_session, project, status="failed", state=_base_state())
    headers = _headers(user)

    async def fake_propose(
        prompt: str, schema: type[AutoFixPatch], **kwargs: object
    ) -> AutoFixPatch:
        return AutoFixPatch(additional_task="Review and confirm the plan is complete.")

    monkeypatch.setattr(auto_fix_mod, "call_model", fake_propose)

    # 1. Trigger the release review -> RCA matches the whitelist -> an
    # "auto_fix" approval is created, the graph "pauses" there.
    resp = await client.post(
        f"/api/v1/projects/{project.id}/runs/{run.id}/release", headers=headers
    )
    assert resp.status_code == 200, resp.text
    snapshot = resp.json()
    assert snapshot["status"] == "awaiting_auto_fix_approval"
    assert snapshot["root_cause_pattern"] == "too_few_tasks"
    assert snapshot["auto_fix_proposed_task"] == "Review and confirm the plan is complete."

    approvals_resp = await client.get("/api/v1/approvals", headers=headers)
    assert approvals_resp.status_code == 200
    pending = approvals_resp.json()
    assert len(pending) == 1
    assert pending[0]["node"] == "auto_fix"
    assert pending[0]["status"] == "pending"
    auto_fix_approval_id = pending[0]["id"]

    # 2. Approve the whitelisted fix -> apply_and_reverify() runs the
    # real (mocked-tool) sandboxed re-verify -> passes -> hard gate
    # passes (no flags) -> a "release_decision" approval is created.
    async def fake_reverify_tool(tool_name: str, arguments: dict[str, object]) -> ToolCallResult:
        assert "Review and confirm the plan is complete." in str(arguments["code"])
        return ToolCallResult(
            tool_name="run_python", input=arguments, output="PASS\n", duration_ms=1, ok=True
        )

    monkeypatch.setattr(auto_fix_mod, "call_tool", fake_reverify_tool)

    resume1 = await client.post(
        f"/api/v1/approvals/{auto_fix_approval_id}/decide",
        json={"approved": True, "reason": "Looks safe."},
        headers=headers,
    )
    assert resume1.status_code == 200, resume1.text
    snapshot2 = resume1.json()
    assert snapshot2["auto_fix_applied"] is True
    assert snapshot2["hard_gate_passed"] is True
    assert snapshot2["status"] == "awaiting_release_approval"

    approvals_resp2 = await client.get("/api/v1/approvals?status_filter=pending", headers=headers)
    pending2 = approvals_resp2.json()
    assert len(pending2) == 1
    assert pending2[0]["node"] == "release_decision"
    release_approval_id = pending2[0]["id"]

    # 3. Approve the Ship proposal -> terminal decision "ship".
    resume2 = await client.post(
        f"/api/v1/approvals/{release_approval_id}/decide",
        json={"approved": True, "reason": "Shipping it."},
        headers=headers,
    )
    assert resume2.status_code == 200, resume2.text
    snapshot3 = resume2.json()
    assert snapshot3["status"] == "done"
    assert snapshot3["decision"] == "ship"

    all_approvals = await client.get("/api/v1/approvals", headers=headers)
    statuses = {a["node"]: a["status"] for a in all_approvals.json()}
    assert statuses == {"auto_fix": "approved", "release_decision": "approved"}


async def test_rejecting_the_auto_fix_proposal_ends_the_workflow(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, project = await _seed_user_and_project(db_session, "release-reject@example.com")
    run = await _seed_run(db_session, project, status="failed", state=_base_state())
    headers = _headers(user)

    async def fake_propose(
        prompt: str, schema: type[AutoFixPatch], **kwargs: object
    ) -> AutoFixPatch:
        return AutoFixPatch(additional_task="Review and confirm the plan is complete.")

    monkeypatch.setattr(auto_fix_mod, "call_model", fake_propose)

    await client.post(f"/api/v1/projects/{project.id}/runs/{run.id}/release", headers=headers)
    pending = (await client.get("/api/v1/approvals", headers=headers)).json()
    approval_id = pending[0]["id"]

    resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decide",
        json={"approved": False, "reason": "Not comfortable auto-patching this."},
        headers=headers,
    )
    assert resp.status_code == 200
    snapshot = resp.json()
    assert snapshot["status"] == "done"
    assert snapshot["auto_fix_applied"] is False
    assert snapshot["decision"] is None


# ---- required blueprint test (also unit-tested directly in
# test_release_decision.py): hard gate holds regardless of everything
# else, exercised end-to-end through the real API this time ----


async def test_a_safety_flag_holds_automatically_without_any_approval(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, project = await _seed_user_and_project(db_session, "release-hold@example.com")
    state = _base_state(
        status="succeeded",
        verification_passed=True,
        plan=["task one", "task two"],
        flags=[_safety_flag()],
    )
    run = await _seed_run(db_session, project, status="succeeded", state=state)
    headers = _headers(user)

    resp = await client.post(
        f"/api/v1/projects/{project.id}/runs/{run.id}/release", headers=headers
    )
    assert resp.status_code == 200
    snapshot = resp.json()
    assert snapshot["hard_gate_passed"] is False
    assert snapshot["status"] == "done"
    assert snapshot["decision"] == "hold"

    approvals = (await client.get("/api/v1/approvals", headers=headers)).json()
    assert approvals == []  # Hold never requires human approval


async def test_rejecting_a_ship_proposal_records_a_rollback(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, project = await _seed_user_and_project(db_session, "release-rollback@example.com")
    state = _base_state(
        status="succeeded", verification_passed=True, plan=["task one", "task two"], flags=[]
    )
    run = await _seed_run(db_session, project, status="succeeded", state=state)
    headers = _headers(user)

    await client.post(f"/api/v1/projects/{project.id}/runs/{run.id}/release", headers=headers)
    pending = (await client.get("/api/v1/approvals", headers=headers)).json()
    approval_id = pending[0]["id"]

    resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decide",
        json={"approved": False, "reason": "Not ready."},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "rollback"


async def test_non_whitelisted_failure_routes_to_a_human_with_no_approval(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, project = await _seed_user_and_project(db_session, "release-nonwhitelist@example.com")
    state = _base_state(flags=[_safety_flag()])
    run = await _seed_run(db_session, project, status="failed", state=state)
    headers = _headers(user)

    async def fake_call_model(
        prompt: str, schema: type[RootCauseHypothesis], **kwargs: object
    ) -> RootCauseHypothesis:
        return RootCauseHypothesis(hypothesis="The verification tool call was blocked by Safety.")

    monkeypatch.setattr(rca_mod, "call_model", fake_call_model)

    resp = await client.post(
        f"/api/v1/projects/{project.id}/runs/{run.id}/release", headers=headers
    )
    assert resp.status_code == 200
    snapshot = resp.json()
    assert snapshot["status"] == "done"
    assert snapshot["root_cause"] == "The verification tool call was blocked by Safety."
    assert snapshot["root_cause_pattern"] is None

    approvals = (await client.get("/api/v1/approvals", headers=headers)).json()
    assert approvals == []


# ---- guards ----


async def test_requesting_release_twice_is_idempotent(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user, project = await _seed_user_and_project(db_session, "release-idempotent@example.com")
    state = _base_state(
        status="succeeded", verification_passed=True, plan=["task one", "task two"], flags=[]
    )
    run = await _seed_run(db_session, project, status="succeeded", state=state)
    headers = _headers(user)

    first = await client.post(
        f"/api/v1/projects/{project.id}/runs/{run.id}/release", headers=headers
    )
    second = await client.post(
        f"/api/v1/projects/{project.id}/runs/{run.id}/release", headers=headers
    )
    assert first.json() == second.json()

    approvals = (await client.get("/api/v1/approvals", headers=headers)).json()
    assert len(approvals) == 1  # not duplicated by the second call


async def test_release_review_rejects_a_run_still_in_progress(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, project = await _seed_user_and_project(db_session, "release-inprogress@example.com")
    run = await _seed_run(
        db_session, project, status="planning", state=_base_state(status="planning")
    )
    headers = _headers(user)

    resp = await client.post(
        f"/api/v1/projects/{project.id}/runs/{run.id}/release", headers=headers
    )
    assert resp.status_code == 409


async def test_deciding_an_already_decided_approval_is_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, project = await _seed_user_and_project(db_session, "release-double-decide@example.com")
    state = _base_state(
        status="succeeded", verification_passed=True, plan=["task one", "task two"], flags=[]
    )
    run = await _seed_run(db_session, project, status="succeeded", state=state)
    headers = _headers(user)

    await client.post(f"/api/v1/projects/{project.id}/runs/{run.id}/release", headers=headers)
    approval_id = (await client.get("/api/v1/approvals", headers=headers)).json()[0]["id"]

    first = await client.post(
        f"/api/v1/approvals/{approval_id}/decide", json={"approved": True}, headers=headers
    )
    assert first.status_code == 200

    second = await client.post(
        f"/api/v1/approvals/{approval_id}/decide", json={"approved": True}, headers=headers
    )
    assert second.status_code == 409


async def test_a_user_cannot_see_or_decide_another_users_approvals(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    owner, project = await _seed_user_and_project(db_session, "release-owner@example.com")
    stranger, _ = await _seed_user_and_project(db_session, "release-stranger@example.com")

    state = _base_state(
        status="succeeded", verification_passed=True, plan=["task one", "task two"], flags=[]
    )
    run = await _seed_run(db_session, project, status="succeeded", state=state)

    await client.post(
        f"/api/v1/projects/{project.id}/runs/{run.id}/release", headers=_headers(owner)
    )

    stranger_approvals = await client.get("/api/v1/approvals", headers=_headers(stranger))
    assert stranger_approvals.json() == []

    owner_approval_id = (
        await client.get("/api/v1/approvals", headers=_headers(owner))
    ).json()[0]["id"]

    forbidden = await client.post(
        f"/api/v1/approvals/{owner_approval_id}/decide",
        json={"approved": True},
        headers=_headers(stranger),
    )
    assert forbidden.status_code == 403


async def test_decide_returns_404_for_an_unknown_approval(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user, _ = await _seed_user_and_project(db_session, "release-unknown-approval@example.com")

    resp = await client.post(
        f"/api/v1/approvals/{uuid.uuid4()}/decide",
        json={"approved": True},
        headers=_headers(user),
    )
    assert resp.status_code == 404


async def test_decide_persists_correctly_across_genuinely_separate_sessions(
    db_session: AsyncSession,
) -> None:
    """See the module docstring for why this test deliberately doesn't use
    the shared `client`/`db_session` fixtures for the workflow steps
    themselves — only to seed the initial rows."""
    user, project = await _seed_user_and_project(db_session, "release-fresh-sessions@example.com")
    state = _base_state(
        status="succeeded", verification_passed=True, plan=["task one", "task two"], flags=[]
    )
    run = await _seed_run(db_session, project, status="succeeded", state=state)
    await db_session.commit()
    run_id = run.id

    engine = create_async_engine(TEST_DATABASE_URL)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    try:
        async with session_factory() as session_a:
            run_repo = RunRepository(session_a)
            run_a = await run_repo.get_by_id(run_id)
            assert run_a is not None
            snapshot = await approvals_service.start_release_review(session_a, run_a)
            assert snapshot["status"] == "awaiting_release_approval"

        async with session_factory() as session_b:
            approvals_repo = ApprovalRepository(session_b)
            approvals = await approvals_repo.list_for_owner(user.id)
            approval = next(a for a in approvals if a.run_id == run_id)
            snapshot = await approvals_service.decide(
                session_b, approval, approved=True, reason="ship it", decided_by=user.id
            )
            assert snapshot["status"] == "done"
            assert snapshot["decision"] == "ship"

        async with session_factory() as session_c:
            run_repo_c = RunRepository(session_c)
            run_c = await run_repo_c.get_by_id(run_id)
            assert run_c is not None
            # The actual regression: without the fix, this still reads
            # back "awaiting_release_approval" / decision=None — the
            # decide() call above appeared to succeed (correct return
            # value) but never actually persisted.
            assert run_c.state["release"]["status"] == "done"
            assert run_c.state["release"]["decision"] == "ship"
    finally:
        await engine.dispose()
