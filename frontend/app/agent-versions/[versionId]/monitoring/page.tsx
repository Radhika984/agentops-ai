"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "../../../components/AppShell";
import { Badge, type Tone } from "../../../components/ui/Badge";
import { Card } from "../../../components/ui/Card";
import { EmptyState } from "../../../components/ui/EmptyState";
import { MetricCard } from "../../../components/ui/MetricCard";
import { Skeleton } from "../../../components/ui/Skeleton";
import { VerdictBanner } from "../../../components/ui/VerdictBanner";
import { CheckIcon, ChevronLeftIcon, CloseIcon, MonitoringIcon, WarningIcon } from "../../../components/ui/icons";
import {
  ApiError,
  clearToken,
  getMonitoringSummary,
  listExecutions,
  type ExecutionVerdict,
  type ProductionExecutionRead,
} from "../../../lib/api";
import { useRequireAuth } from "../../../lib/useRequireAuth";

function verdictTone(verdict: ExecutionVerdict): Tone {
  if (verdict === "PASS") return "success";
  if (verdict === "FAIL") return "danger";
  return "warning";
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function formatRate(rate: number | null): string {
  if (rate === null) return "—";
  return `${Math.round(rate * 100)}%`;
}

/** A short, factual summary of why an execution's checks are notable —
 * derived entirely from the persisted checks[] already returned by the
 * list endpoint, never a fabricated label. Empty string when nothing
 * failed (a clean PASS/INCONCLUSIVE row shows no summary chip). */
function checkSummary(execution: ProductionExecutionRead): string | null {
  const failing = execution.checks.filter((c) => c.status === "fail");
  if (failing.length === 0) return null;
  const types = [...new Set(failing.map((c) => c.check_type.split(":")[0].split("[")[0]))];
  return `${failing.length} check${failing.length === 1 ? "" : "s"} failed (${types.join(", ")})`;
}

export default function AgentVersionMonitoringPage() {
  const { versionId } = useParams<{ versionId: string }>();
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  const summaryQuery = useQuery({
    queryKey: ["monitoring-summary", versionId],
    queryFn: () => getMonitoringSummary(versionId),
    enabled: checkedAuth,
  });

  const executionsQuery = useQuery({
    queryKey: ["executions", versionId],
    queryFn: () => listExecutions(versionId),
    enabled: checkedAuth,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const summary = summaryQuery.data;
  const executions = executionsQuery.data;

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href="/monitoring"
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        Monitoring
      </Link>
      <p className="truncate font-mono text-sm font-semibold text-ink">{versionId}</p>
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-5xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Agent Version monitoring</h1>
        <p className="mt-1.5 max-w-2xl truncate font-mono text-xs text-ink-3">{versionId}</p>

        {summaryQuery.isLoading && (
          <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
            {[0, 1, 2, 3, 4, 5, 6, 7].map((i) => (
              <Skeleton key={i} className="h-20" />
            ))}
          </div>
        )}

        {summaryQuery.isError && (
          <p className="mt-6 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {summaryQuery.error instanceof ApiError
              ? summaryQuery.error.message
              : "Could not load the monitoring summary."}
          </p>
        )}

        {summary && summary.total_executions === 0 && (
          <div className="mt-6">
            <EmptyState
              icon={<MonitoringIcon />}
              title="No monitoring data yet"
              description="No post-release executions have been ingested for this Agent Version yet."
            />
          </div>
        )}

        {summary && summary.total_executions > 0 && (
          <>
            {/* Dominant health signal first, then the pass/fail/
                inconclusive counts it's built from, then the 8 remaining
                technical metrics demoted to a denser secondary row —
                not 12 equal tiles with failure rate buried among them. */}
            <div className="mt-6">
              <VerdictBanner
                tone={summary.fail_count > 0 ? "danger" : summary.inconclusive_count > 0 ? "warning" : "success"}
                icon={
                  summary.fail_count > 0 ? <CloseIcon /> : summary.inconclusive_count > 0 ? <WarningIcon /> : <CheckIcon />
                }
                headline={`${formatRate(summary.failure_rate)} failure rate across ${summary.total_executions} execution${summary.total_executions === 1 ? "" : "s"}`}
              />
            </div>

            <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
              <MetricCard label="Total executions" value={String(summary.total_executions)} />
              <MetricCard label="Pass" value={String(summary.pass_count)} tone="success" />
              <MetricCard label="Fail" value={String(summary.fail_count)} tone="danger" />
              <MetricCard label="Inconclusive" value={String(summary.inconclusive_count)} tone="warning" />
            </div>

            <div className="mt-5">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">Technical detail</p>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                <MetricCard
                  label="Avg latency"
                  value={summary.average_latency_ms !== null ? formatMs(summary.average_latency_ms) : "—"}
                />
                <MetricCard label="Latency violations" value={String(summary.latency_threshold_violations)} />
                <MetricCard label="Safety failures" value={String(summary.safety_failure_count)} tone={summary.safety_failure_count > 0 ? "danger" : undefined} />
                <MetricCard label="Forbidden tool calls" value={String(summary.forbidden_tool_count)} tone={summary.forbidden_tool_count > 0 ? "danger" : undefined} />
                <MetricCard label="Missing required tools" value={String(summary.missing_required_tool_count)} />
                <MetricCard label="Schema failures" value={String(summary.schema_failure_count)} />
                <MetricCard
                  label="Grounding failures"
                  value={
                    summary.grounding_evaluated_count > 0
                      ? `${summary.grounding_failure_count} / ${summary.grounding_evaluated_count}`
                      : "—"
                  }
                  hint={summary.grounding_evaluated_count === 0 ? "Not evaluated (no reference context)" : undefined}
                />
              </div>
            </div>

            <div className="mt-7">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">
                Recent executions
              </p>

              {executionsQuery.isLoading && (
                <div className="flex flex-col gap-2">
                  <Skeleton className="h-12" />
                  <Skeleton className="h-12" />
                  <Skeleton className="h-12" />
                </div>
              )}

              {executionsQuery.isError && (
                <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                  {executionsQuery.error instanceof ApiError
                    ? executionsQuery.error.message
                    : "Could not load executions."}
                </p>
              )}

              {executions && executions.length === 0 && (
                <EmptyState title="No executions yet" description="Ingested executions will appear here." />
              )}

              {executions && executions.length > 0 && (
                <Card padded={false} className="overflow-x-auto">
                  <table className="w-full min-w-150 text-left text-sm">
                    <thead>
                      <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-3">
                        <th className="px-4 py-2.5 font-medium">Verdict</th>
                        <th className="px-4 py-2.5 font-medium">External ID</th>
                        <th className="px-4 py-2.5 font-medium">Summary</th>
                        <th className="px-4 py-2.5 text-right font-medium">Latency</th>
                        <th className="px-4 py-2.5 text-right font-medium">Ingested</th>
                      </tr>
                    </thead>
                    <tbody>
                      {executions.map((execution) => {
                        const openExecution = () =>
                          router.push(`/agent-versions/${versionId}/executions/${execution.id}`);
                        return (
                        <tr
                          key={execution.id}
                          onClick={openExecution}
                          tabIndex={0}
                          role="button"
                          onKeyDown={(e) => {
                            if (e.key === "Enter" || e.key === " ") {
                              e.preventDefault();
                              openExecution();
                            }
                          }}
                          className="cursor-pointer border-b border-line text-ink-2 transition-colors duration-150 last:border-b-0 hover:bg-surface-2 focus-visible:bg-surface-2 focus-visible:outline-none"
                        >
                          <td className="px-4 py-2.5">
                            <Badge tone={verdictTone(execution.verdict)}>{execution.verdict}</Badge>
                          </td>
                          <td className="px-4 py-2.5 font-mono text-xs text-ink">
                            {execution.external_execution_id}
                          </td>
                          <td className="px-4 py-2.5 text-xs text-ink-3">
                            {checkSummary(execution) ?? "—"}
                          </td>
                          <td className="px-4 py-2.5 text-right tabular-nums">
                            {execution.latency_ms !== null ? formatMs(execution.latency_ms) : "—"}
                          </td>
                          <td className="px-4 py-2.5 text-right text-xs whitespace-nowrap text-ink-3">
                            {new Date(execution.created_at).toLocaleString()}
                          </td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </Card>
              )}
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
