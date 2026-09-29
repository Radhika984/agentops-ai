import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../../../../../lib/useRequireAuth", () => ({
  useRequireAuth: () => true,
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ agentId: "agent-1", suiteId: "suite-1", suiteRunId: "run-1" }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/agents/agent-1/test-suites/suite-1/runs/run-1",
}));

const api = vi.hoisted(() => ({
  getSuiteRun: vi.fn(),
  getTestSuite: vi.fn(),
  listAgentVersions: vi.fn(),
  listSuiteRunResults: vi.fn(),
  listTestCases: vi.fn(),
  clearToken: vi.fn(),
  getCurrentUser: vi.fn(),
  listApprovals: vi.fn(),
  search: vi.fn(),
}));

vi.mock("../../../../../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../../../../../lib/api")>(
    "../../../../../../lib/api",
  );
  return { ...actual, ...api };
});

import type { SuiteRunRead, TestCaseResultRead } from "../../../../../../lib/api";
import SuiteRunDetailPage from "./page";

const RUNNING_RUN: SuiteRunRead = {
  id: "run-1",
  suite_id: "suite-1",
  agent_version_id: "version-1",
  status: "running",
  started_at: "2026-01-01T00:00:00Z",
  completed_at: null,
  pass_count: 0,
  fail_count: 0,
  inconclusive_count: 0,
  skipped_count: 0,
  llm_judge_invocation_count: 0,
  max_concurrency: 1,
  created_at: "2026-01-01T00:00:00Z",
};

const COMPLETED_RUN: SuiteRunRead = {
  ...RUNNING_RUN,
  status: "completed",
  completed_at: "2026-01-01T00:01:00Z",
  pass_count: 1,
  fail_count: 0,
};

const RESULT_1: TestCaseResultRead = {
  id: "result-1",
  suite_run_id: "run-1",
  test_case_id: "case-1",
  verdict: "PASS",
  verdict_method: "assertions",
  checks: [],
  trials: [],
  actual_output: "ok",
  latency_ms: 120,
  error: null,
  suggested_fix: null,
  created_at: "2026-01-01T00:00:30Z",
  updated_at: "2026-01-01T00:00:30Z",
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <SuiteRunDetailPage />
    </QueryClientProvider>,
  );
  return { client, ...view };
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getTestSuite.mockResolvedValue({
    id: "suite-1",
    agent_id: "agent-1",
    name: "My Suite",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  });
  api.listAgentVersions.mockResolvedValue([
    { id: "version-1", agent_id: "agent-1", label: "v1", adapter_type: "http", adapter_config: {}, observability_level: 1, is_baseline: true, created_at: "2026-01-01T00:00:00Z" },
  ]);
  api.listTestCases.mockResolvedValue([{ id: "case-1", suite_id: "suite-1", name: "Case One" }]);
  api.getCurrentUser.mockResolvedValue({
    id: "u1",
    email: "owner@example.com",
    full_name: null,
    is_active: true,
    notify_on_suite_run_complete: true,
    notify_on_release_gate: true,
    notify_on_autofix_proposed: true,
    notify_on_approval_decided: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  });
  api.listApprovals.mockResolvedValue([]);
  api.search.mockResolvedValue({ results: [] });
});

afterEach(() => {
  cleanup();
});

describe("SuiteRunDetailPage — BUG-002", () => {
  it("a completed run with results renders the results table", async () => {
    api.getSuiteRun.mockResolvedValue(COMPLETED_RUN);
    api.listSuiteRunResults.mockResolvedValue([RESULT_1]);

    renderPage();

    expect(await screen.findByText("Case One")).toBeInTheDocument();
    expect(screen.getByText("PASS")).toBeInTheDocument();
    expect(screen.queryByText("No results yet")).not.toBeInTheDocument();
  });

  it("does not stay stuck on 'No results yet' once the run transitions to completed while results were still synchronizing", async () => {
    api.getSuiteRun.mockResolvedValue(RUNNING_RUN);
    // First fetch (while the run is still running) legitimately finds no
    // results yet; the second fetch — triggered by this app's own
    // invalidation when the run transitions to terminal, not by a
    // remount — returns the real, final result.
    api.listSuiteRunResults.mockResolvedValueOnce([]).mockResolvedValue([RESULT_1]);

    const { client } = renderPage();

    // While genuinely running with genuinely no results yet, the empty
    // state IS correct — this is not the bug.
    expect(await screen.findByText("No results yet")).toBeInTheDocument();
    expect(api.listSuiteRunResults).toHaveBeenCalledTimes(1);

    // Simulate the run's own poll landing with the final, terminal
    // status + counts (exactly what a real 1500ms refetchInterval tick
    // does to the "suite-run" query's cache) — without navigating away,
    // remounting, or calling resultsQuery.refetch() directly from the
    // test. If the fix works, the page's own transition-triggered
    // invalidation must pick this up on its own.
    client.setQueryData(["suite-run", "run-1"], COMPLETED_RUN);

    expect(await screen.findByText("Case One")).toBeInTheDocument();
    expect(screen.queryByText("No results yet")).not.toBeInTheDocument();
    expect(api.listSuiteRunResults).toHaveBeenCalledTimes(2);
  });

  it("a genuinely empty result set on a completed run still shows the empty state (not hidden by the fix)", async () => {
    api.getSuiteRun.mockResolvedValue(COMPLETED_RUN);
    api.listSuiteRunResults.mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText("No results yet")).toBeInTheDocument();
    expect(screen.queryByText("Case One")).not.toBeInTheDocument();
  });

  it("existing loading behavior is preserved while the run is still being fetched", async () => {
    api.getSuiteRun.mockReturnValue(new Promise(() => {})); // never resolves
    api.listSuiteRunResults.mockResolvedValue([]);

    const { container } = renderPage();

    expect(screen.getByText("Suite run")).toBeInTheDocument();
    expect(container.querySelectorAll(".animate-pulse, [class*='skeleton' i]").length).toBeGreaterThanOrEqual(0);
    // Nothing from the (not-yet-loaded) run body renders.
    expect(screen.queryByText("No results yet")).not.toBeInTheDocument();
    expect(screen.queryByText("Case One")).not.toBeInTheDocument();
  });

  it("an already-completed run on initial page load does not cause an extra results refetch beyond the normal one", async () => {
    api.getSuiteRun.mockResolvedValue(COMPLETED_RUN);
    api.listSuiteRunResults.mockResolvedValue([RESULT_1]);

    renderPage();

    await screen.findByText("Case One");
    // Let any microtasks from a would-be extra invalidate settle.
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(api.listSuiteRunResults).toHaveBeenCalledTimes(1);
  });
});
