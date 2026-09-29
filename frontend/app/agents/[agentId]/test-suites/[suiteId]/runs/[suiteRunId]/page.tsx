"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../../../../../../components/AppShell";
import { Badge, type Tone } from "../../../../../../components/ui/Badge";
import { Button } from "../../../../../../components/ui/Button";
import { Card } from "../../../../../../components/ui/Card";
import { EmptyState } from "../../../../../../components/ui/EmptyState";
import { Skeleton } from "../../../../../../components/ui/Skeleton";
import { StatusLabel } from "../../../../../../components/ui/Status";
import { ChevronLeftIcon, VerifyIcon } from "../../../../../../components/ui/icons";
import {
  ApiError,
  clearToken,
  getSuiteRun,
  getTestSuite,
  listAgentVersions,
  listSuiteRunResults,
  listTestCases,
  type SuiteRunStatus,
  type TestCaseResultRead,
  type Verdict,
} from "../../../../../../lib/api";
import { useRequireAuth } from "../../../../../../lib/useRequireAuth";

const TERMINAL_STATUSES: SuiteRunStatus[] = ["completed", "failed"];
const POLL_INTERVAL_MS = 1500;

function statusTone(status: SuiteRunStatus): Tone {
  if (status === "completed") return "success";
  if (status === "failed") return "danger";
  if (status === "cancelling") return "warning";
  if (status === "running") return "accent";
  return "neutral";
}

function verdictTone(verdict: Verdict): Tone {
  if (verdict === "PASS") return "success";
  if (verdict === "FAIL") return "danger";
  return "warning";
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function formatTimestamp(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

const METRIC_VALUE_TONE: Record<Tone, string> = {
  neutral: "text-ink",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  accent: "text-accent",
};

function MetricCard({ label, value, tone = "neutral" }: { label: string; value: string; tone?: Tone }) {
  return (
    <Card elevation="raised">
      <p className="text-xs font-medium tracking-wide text-ink-3 uppercase">{label}</p>
      <p className={`mt-2 text-2xl font-bold tracking-tight ${METRIC_VALUE_TONE[tone]}`}>{value}</p>
    </Card>
  );
}

/** A short, factual summary of what's notable about a result's checks —
 * derived entirely from the persisted checks[] the results endpoint
 * already returns, never a fabricated label. */
function checkSummary(result: TestCaseResultRead): string | null {
  const failing = result.checks.filter((c) => c.status === "fail");
  if (failing.length === 0) return null;
  const types = [...new Set(failing.map((c) => c.check_type.split(":")[0].split("[")[0]))];
  return `${failing.length} check${failing.length === 1 ? "" : "s"} failed (${types.join(", ")})`;
}

export default function SuiteRunDetailPage() {
  const { agentId, suiteId, suiteRunId } = useParams<{
    agentId: string;
    suiteId: string;
    suiteRunId: string;
  }>();
  const router = useRouter();
  const checkedAuth = useRequireAuth();
  const queryClient = useQueryClient();

  const runQuery = useQuery({
    queryKey: ["suite-run", suiteRunId],
    queryFn: () => getSuiteRun(suiteRunId),
    enabled: checkedAuth,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL_STATUSES.includes(status) ? false : POLL_INTERVAL_MS;
    },
  });

  const suiteQuery = useQuery({
    queryKey: ["test-suite", agentId, suiteId],
    queryFn: () => getTestSuite(agentId, suiteId),
    enabled: checkedAuth,
  });

  const versionsQuery = useQuery({
    queryKey: ["agent-versions", agentId],
    queryFn: () => listAgentVersions(agentId),
    enabled: checkedAuth,
  });

  const casesQuery = useQuery({
    queryKey: ["test-cases", suiteId],
    queryFn: () => listTestCases(suiteId),
    enabled: checkedAuth,
  });

  const run = runQuery.data;
  const hasStarted = run !== undefined && run.status !== "pending";

  const resultsQuery = useQuery({
    queryKey: ["suite-run-results", suiteRunId],
    queryFn: () => listSuiteRunResults(suiteRunId),
    enabled: checkedAuth && hasStarted,
    refetchInterval: () => (run && !TERMINAL_STATUSES.includes(run.status) ? POLL_INTERVAL_MS : false),
  });

  // BUG-002: runQuery and resultsQuery poll on independent, unsynchronized
  // 1500ms timers. resultsQuery's own refetchInterval above turns polling
  // off the instant `run.status` becomes terminal — but if the run
  // finishes in between two of resultsQuery's own polls, the poll that
  // would have fetched the final, complete result set never fires: it
  // gets cancelled as soon as this component re-renders with the new
  // terminal status. That leaves resultsQuery's cache stuck on whatever
  // partial/empty data it last fetched while the run was still in
  // progress, even though the summary counters (read straight off the
  // now-terminal `run` object) already show the final numbers — exactly
  // the "No results yet" + final counters seen together bug. One
  // guaranteed invalidation exactly at the running→terminal transition
  // (not a delay, not disabling the empty state) closes that gap; the
  // `previousStatus` ref keeps this from re-firing on every render or
  // from re-invalidating a run that was already terminal on page load.
  const previousStatus = useRef<SuiteRunStatus | undefined>(undefined);
  useEffect(() => {
    const status = run?.status;
    const previous = previousStatus.current;
    if (
      status &&
      TERMINAL_STATUSES.includes(status) &&
      previous !== undefined &&
      !TERMINAL_STATUSES.includes(previous)
    ) {
      queryClient.invalidateQueries({ queryKey: ["suite-run-results", suiteRunId] });
    }
    previousStatus.current = status;
  }, [run?.status, queryClient, suiteRunId]);

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const version = versionsQuery.data?.find((v) => v.id === run?.agent_version_id);
  const caseNameById = new Map((casesQuery.data ?? []).map((c) => [c.id, c.name]));
  const results = resultsQuery.data ?? [];
  const isPolling = run !== undefined && !TERMINAL_STATUSES.includes(run.status);

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href={`/agents/${agentId}/test-suites/${suiteId}`}
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        {suiteQuery.data?.name ?? "Test suite"}
      </Link>
      <p className="truncate font-mono text-sm font-semibold text-ink">{suiteRunId}</p>
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-3xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Suite run</h1>

        {runQuery.isLoading && (
          <div className="mt-6 flex flex-col gap-3">
            <Skeleton className="h-20" />
            <Skeleton className="h-40" />
          </div>
        )}

        {runQuery.isError && (
          <p className="mt-6 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {runQuery.error instanceof ApiError ? runQuery.error.message : "Could not load this suite run."}
          </p>
        )}

        {run && (
          <>
            <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
              <div className="flex flex-wrap items-center gap-3">
                <StatusLabel tone={statusTone(run.status)} pulse={isPolling}>
                  {run.status}
                </StatusLabel>
                <span className="text-sm text-ink-2">
                  {version ? version.label : run.agent_version_id}
                  {version?.is_baseline && (
                    <Badge tone="accent">
                      <span className="ml-1">baseline</span>
                    </Badge>
                  )}
                </span>
              </div>

              {TERMINAL_STATUSES.includes(run.status) && (
                <div className="flex flex-wrap gap-2">
                  <Link
                    href={`/agents/${agentId}/test-suites/${suiteId}/runs/${suiteRunId}/regression`}
                    className="no-underline"
                  >
                    <Button variant="secondary" size="sm">
                      Compare with baseline
                    </Button>
                  </Link>
                  <Link
                    href={`/agents/${agentId}/test-suites/${suiteId}/runs/${suiteRunId}/release`}
                    className="no-underline"
                  >
                    <Button variant="secondary" size="sm">
                      Review release
                    </Button>
                  </Link>
                </div>
              )}
            </div>

            <div className="mt-3 grid grid-cols-2 gap-3 text-xs text-ink-3 sm:grid-cols-4">
              <div>
                <p className="uppercase tracking-wide">Created</p>
                <p className="mt-0.5 text-ink-2">{formatTimestamp(run.created_at)}</p>
              </div>
              <div>
                <p className="uppercase tracking-wide">Started</p>
                <p className="mt-0.5 text-ink-2">{formatTimestamp(run.started_at)}</p>
              </div>
              <div>
                <p className="uppercase tracking-wide">Completed</p>
                <p className="mt-0.5 text-ink-2">{formatTimestamp(run.completed_at)}</p>
              </div>
              <div>
                <p className="uppercase tracking-wide">Max concurrency</p>
                <p className="mt-0.5 text-ink-2">{run.max_concurrency}</p>
              </div>
            </div>

            <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
              <MetricCard label="Pass" value={String(run.pass_count)} tone="success" />
              <MetricCard label="Fail" value={String(run.fail_count)} tone="danger" />
              <MetricCard label="Inconclusive" value={String(run.inconclusive_count)} tone="warning" />
              <MetricCard label="Skipped" value={String(run.skipped_count)} />
              <MetricCard label="LLM judge calls" value={String(run.llm_judge_invocation_count)} />
            </div>

            <div className="mt-7">
              <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Results</p>

              <div className="mt-3 flex flex-col gap-3">
                {!hasStarted && (
                  <p className="rounded-md border border-dashed border-line-strong px-4 py-6 text-center text-sm text-ink-3">
                    Waiting for this run to start…
                  </p>
                )}

                {hasStarted && resultsQuery.isLoading && (
                  <>
                    <Skeleton className="h-16" />
                    <Skeleton className="h-16" />
                  </>
                )}

                {hasStarted && resultsQuery.isError && (
                  <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                    {resultsQuery.error instanceof ApiError
                      ? resultsQuery.error.message
                      : "Could not load results."}
                  </p>
                )}

                {hasStarted &&
                  resultsQuery.data &&
                  results.length === 0 &&
                  run.status === "failed" && (
                    <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                      This suite run failed before producing any results.
                    </p>
                  )}

                {hasStarted && resultsQuery.data && results.length === 0 && run.status !== "failed" && (
                  <EmptyState
                    icon={<VerifyIcon />}
                    title="No results yet"
                    description="Results will appear here as each test case finishes executing."
                  />
                )}

                {results.length > 0 && (
                  <Card padded={false} className="overflow-x-auto">
                    <table className="w-full min-w-150 text-left text-sm">
                      <thead>
                        <tr className="border-b border-line text-xs tracking-wide text-ink-3 uppercase">
                          <th className="px-4 py-2.5 font-medium">Verdict</th>
                          <th className="px-4 py-2.5 font-medium">Test case</th>
                          <th className="px-4 py-2.5 font-medium">Summary</th>
                          <th className="px-4 py-2.5 text-right font-medium">Latency</th>
                        </tr>
                      </thead>
                      <tbody>
                        {results.map((result) => {
                          const openResult = () =>
                            router.push(
                              `/agents/${agentId}/test-suites/${suiteId}/runs/${suiteRunId}/results/${result.id}`,
                            );
                          return (
                          <tr
                            key={result.id}
                            onClick={openResult}
                            tabIndex={0}
                            role="button"
                            onKeyDown={(e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                openResult();
                              }
                            }}
                            className="cursor-pointer border-b border-line text-ink-2 transition-colors duration-150 last:border-b-0 hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:outline-none"
                          >
                            <td className="px-4 py-2.5">
                              <Badge tone={verdictTone(result.verdict)}>{result.verdict}</Badge>
                            </td>
                            <td className="px-4 py-2.5 text-ink">
                              {caseNameById.get(result.test_case_id) ?? result.test_case_id}
                            </td>
                            <td className="px-4 py-2.5 text-xs text-ink-3">
                              {result.error ?? checkSummary(result) ?? "—"}
                            </td>
                            <td className="px-4 py-2.5 text-right tabular-nums">
                              {result.latency_ms !== null ? formatMs(result.latency_ms) : "—"}
                            </td>
                          </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </Card>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
