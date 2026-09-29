import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mocked before importing the page under test so every module that
// resolves to these files (the page itself, AppShell, etc.) shares one
// mock, regardless of the relative path each one imports it by.
vi.mock("../../lib/useRequireAuth", () => ({
  useRequireAuth: () => true,
}));

const nav = vi.hoisted(() => ({
  replace: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useParams: () => ({ agentId: "agent-a" }),
  useRouter: () => nav,
  usePathname: () => "/agents/agent-a",
}));

const api = vi.hoisted(() => ({
  getAgent: vi.fn(),
  listAgentVersions: vi.fn(),
  listTestSuites: vi.fn(),
  promoteBaseline: vi.fn(),
  getCurrentUser: vi.fn(),
  listApprovals: vi.fn(),
  search: vi.fn(),
  clearToken: vi.fn(),
  getToken: vi.fn(() => "fake-token"),
}));

vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, ...api };
});

import { ApiError } from "../../lib/api";
import { shouldRetry } from "../../lib/queryClient";
import AgentDetailPage from "./page";

const AGENT_A = {
  id: "agent-a",
  project_id: "project-a",
  name: "Account A's Agent",
  description: "Owned by account A — never account B.",
  is_enabled: true,
  default_expected_behavior: null,
  default_forbidden_behavior: null,
  default_output_schema: null,
  default_latency_threshold_ms: null,
  default_allowed_tools: null,
  default_required_tools: null,
  min_call_interval_ms: 0,
  default_timeout_ms: 30000,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function renderPage() {
  // Real production retry policy (shouldRetry), but with retryDelay
  // zeroed out so a query that DOES legitimately retry (5xx) doesn't
  // make the test wait through react-query's real exponential backoff.
  // The retry *count* behavior under test is exactly what shouldRetry()
  // already proves in queryClient.test.ts — this only speeds up the
  // timer, it does not change what gets retried.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: shouldRetry, retryDelay: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <AgentDetailPage />
    </QueryClientProvider> as ReactNode,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
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
  vi.restoreAllMocks();
});

describe("AgentDetailPage — BUG-004", () => {
  it("owner: loads and renders their own agent, versions, and test suites normally", async () => {
    api.getAgent.mockResolvedValue(AGENT_A);
    api.listAgentVersions.mockResolvedValue([]);
    api.listTestSuites.mockResolvedValue([]);

    renderPage();

    expect(await screen.findByRole("heading", { name: "Account A's Agent" })).toBeInTheDocument();
    expect(screen.getByText("Owned by account A — never account B.")).toBeInTheDocument();
    expect(screen.getByText("No versions yet")).toBeInTheDocument();
    expect(screen.getByText("No test suites yet")).toBeInTheDocument();

    expect(api.getAgent).toHaveBeenCalledTimes(1);
    expect(api.listAgentVersions).toHaveBeenCalledTimes(1);
    expect(api.listTestSuites).toHaveBeenCalledTimes(1);
  });

  it("non-owner: 403 renders a clear unauthorized state, not a blank page, and does not leak agent data", async () => {
    api.getAgent.mockRejectedValue(new ApiError(403, "Not authorized for this resource"));
    api.listAgentVersions.mockRejectedValue(new ApiError(403, "Not authorized for this resource"));
    api.listTestSuites.mockRejectedValue(new ApiError(403, "Not authorized for this resource"));

    renderPage();

    expect(await screen.findByText("You don't have access to this agent")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Agents" })).toBeInTheDocument();

    // No trace of Account A's agent anywhere in the DOM.
    expect(screen.queryByText("Account A's Agent")).not.toBeInTheDocument();
    expect(screen.queryByText("Owned by account A — never account B.")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Account A's Agent" })).not.toBeInTheDocument();
  });

  it("non-owner: a terminal 403 does not trigger a retry/request-loop", async () => {
    api.getAgent.mockRejectedValue(new ApiError(403, "Not authorized for this resource"));
    api.listAgentVersions.mockRejectedValue(new ApiError(403, "Not authorized for this resource"));
    api.listTestSuites.mockRejectedValue(new ApiError(403, "Not authorized for this resource"));

    renderPage();

    await screen.findByText("You don't have access to this agent");

    // Give any latent retry/remount loop a real chance to fire before
    // asserting it didn't — this is exactly the "wait long enough to
    // detect a delayed retry" requirement, just at unit-test speed
    // since retryDelay is zeroed above.
    await new Promise((resolve) => setTimeout(resolve, 300));

    expect(api.getAgent).toHaveBeenCalledTimes(1);
    expect(api.listAgentVersions).toHaveBeenCalledTimes(1);
    expect(api.listTestSuites).toHaveBeenCalledTimes(1);
  });

  it("nonexistent agent: 404 is shown distinctly from the 403 unauthorized case", async () => {
    api.getAgent.mockRejectedValue(new ApiError(404, "Agent not found: does-not-exist"));
    api.listAgentVersions.mockRejectedValue(new ApiError(404, "Agent not found: does-not-exist"));
    api.listTestSuites.mockRejectedValue(new ApiError(404, "Agent not found: does-not-exist"));

    renderPage();

    expect(await screen.findByText("Agent not found")).toBeInTheDocument();
    expect(screen.queryByText("You don't have access to this agent")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to Agents" })).toBeInTheDocument();
    expect(api.getAgent).toHaveBeenCalledTimes(1);
  });

  it("a 5xx/transient error still uses the generic error message, not the unauthorized state", async () => {
    api.getAgent.mockRejectedValue(new ApiError(500, "Unexpected error"));
    api.listAgentVersions.mockRejectedValue(new ApiError(500, "Unexpected error"));
    api.listTestSuites.mockRejectedValue(new ApiError(500, "Unexpected error"));

    renderPage();

    await waitFor(() => expect(screen.getByText("Unexpected error")).toBeInTheDocument());
    expect(screen.queryByText("You don't have access to this agent")).not.toBeInTheDocument();
    expect(screen.queryByText("Agent not found")).not.toBeInTheDocument();

    // Unlike a 4xx, a 5xx is retried (matching the pre-existing retry:3
    // default) — 1 initial attempt + 3 retries = 4 calls.
    expect(api.getAgent).toHaveBeenCalledTimes(4);
  });
});
