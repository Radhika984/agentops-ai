"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "../../../../../../../components/AppShell";
import { Badge, type Tone } from "../../../../../../../components/ui/Badge";
import { Card } from "../../../../../../../components/ui/Card";
import { LabeledCodeBlock } from "../../../../../../../components/ui/CodeDisclosure";
import { EmptyState } from "../../../../../../../components/ui/EmptyState";
import { MetricCard } from "../../../../../../../components/ui/MetricCard";
import { Skeleton } from "../../../../../../../components/ui/Skeleton";
import { ChevronLeftIcon, VerifyIcon } from "../../../../../../../components/ui/icons";
import {
  ApiError,
  clearToken,
  getRegression,
  listAgentVersions,
  listTestCases,
  type CaseComparison,
  type RegressionClassification,
} from "../../../../../../../lib/api";
import { useRequireAuth } from "../../../../../../../lib/useRequireAuth";

function classificationTone(c: RegressionClassification): Tone {
  if (c === "regression") return "danger";
  if (c === "improvement") return "success";
  if (c === "changed") return "warning";
  return "neutral";
}

function verdictTone(verdict: string): Tone {
  if (verdict === "PASS") return "success";
  if (verdict === "FAIL") return "danger";
  return "warning";
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function formatRate(rate: number | null): string {
  return rate === null ? "—" : `${Math.round(rate * 100)}%`;
}

function formatOutput(value: unknown): string {
  if (value === null || value === undefined) return "(no output)";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

function CaseRow({ comparison, caseName }: { comparison: CaseComparison; caseName: string }) {
  const { output_diff, tool_trajectory_diff, latency_diff, safety_diff, grounding_diff, trial_summary } =
    comparison;
  const hasDetail =
    output_diff.output_changed ||
    tool_trajectory_diff.changed ||
    latency_diff.available ||
    safety_diff.changed ||
    grounding_diff.changed ||
    trial_summary.baseline_trial_verdicts.length > 0 ||
    trial_summary.candidate_trial_verdicts.length > 0;

  return (
    <Card elevation="raised">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-semibold text-ink">{caseName}</p>
            <Badge tone={classificationTone(comparison.classification)}>{comparison.classification}</Badge>
          </div>
          <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
            <Badge tone={verdictTone(comparison.baseline_verdict)}>{comparison.baseline_verdict}</Badge>
            <span>→</span>
            <Badge tone={verdictTone(comparison.candidate_verdict)}>{comparison.candidate_verdict}</Badge>
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {latency_diff.changed && <Badge tone="neutral">latency changed</Badge>}
          {tool_trajectory_diff.changed && <Badge tone="neutral">tools changed</Badge>}
          {safety_diff.changed && <Badge tone="danger">safety changed</Badge>}
          {grounding_diff.changed && <Badge tone="warning">grounding changed</Badge>}
        </div>
      </div>

      {hasDetail && (
        <details className="group mt-3 border-t border-line pt-3">
          <summary className="cursor-pointer list-none text-xs font-medium text-accent [&::-webkit-details-marker]:hidden">
            View diff details
          </summary>
          <div className="mt-2 flex flex-col gap-3 text-xs">
            {output_diff.output_changed && (
              <div>
                <p className="font-semibold tracking-wide text-ink-3 uppercase">Output</p>
                <div className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <LabeledCodeBlock label="Baseline" value={formatOutput(output_diff.baseline_output)} />
                  <LabeledCodeBlock label="Candidate" value={formatOutput(output_diff.candidate_output)} />
                </div>
              </div>
            )}

            {tool_trajectory_diff.changed && (
              <div>
                <p className="font-semibold tracking-wide text-ink-3 uppercase">Tool trajectory</p>
                <dl className="mt-1 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div>
                    <dt className="text-[10px] tracking-wide text-ink-3 uppercase">Baseline tools</dt>
                    <dd className="mt-0.5 text-ink-2">{tool_trajectory_diff.baseline_tools.join(", ") || "—"}</dd>
                  </div>
                  <div>
                    <dt className="text-[10px] tracking-wide text-ink-3 uppercase">Candidate tools</dt>
                    <dd className="mt-0.5 text-ink-2">{tool_trajectory_diff.candidate_tools.join(", ") || "—"}</dd>
                  </div>
                  {tool_trajectory_diff.added_tools.length > 0 && (
                    <div>
                      <dt className="text-[10px] tracking-wide text-ink-3 uppercase">Added</dt>
                      <dd className="mt-0.5 text-success">{tool_trajectory_diff.added_tools.join(", ")}</dd>
                    </div>
                  )}
                  {tool_trajectory_diff.removed_tools.length > 0 && (
                    <div>
                      <dt className="text-[10px] tracking-wide text-ink-3 uppercase">Removed</dt>
                      <dd className="mt-0.5 text-danger">{tool_trajectory_diff.removed_tools.join(", ")}</dd>
                    </div>
                  )}
                  {tool_trajectory_diff.order_changed && (
                    <div className="sm:col-span-2 text-ink-2">Call order changed.</div>
                  )}
                  {tool_trajectory_diff.argument_changes.length > 0 && (
                    <div className="sm:col-span-2">
                      <dt className="text-[10px] tracking-wide text-ink-3 uppercase">Argument changes</dt>
                      <dd className="mt-0.5 text-ink-2">{tool_trajectory_diff.argument_changes.join(", ")}</dd>
                    </div>
                  )}
                </dl>
              </div>
            )}

            {latency_diff.available && (
              <div>
                <p className="font-semibold tracking-wide text-ink-3 uppercase">Latency</p>
                <p className="mt-1 text-ink-2">
                  {latency_diff.baseline_latency_ms !== null ? formatMs(latency_diff.baseline_latency_ms) : "—"}
                  {" → "}
                  {latency_diff.candidate_latency_ms !== null ? formatMs(latency_diff.candidate_latency_ms) : "—"}
                  {latency_diff.delta_ms !== null &&
                    ` (${latency_diff.delta_ms >= 0 ? "+" : ""}${latency_diff.delta_ms}ms)`}
                </p>
              </div>
            )}

            {safety_diff.changed && (
              <div>
                <p className="font-semibold tracking-wide text-ink-3 uppercase">Safety</p>
                <p className="mt-1 text-ink-2">
                  {safety_diff.baseline_status} → {safety_diff.candidate_status}
                </p>
                {safety_diff.newly_unsafe.length > 0 && (
                  <p className="mt-0.5 text-danger">Newly unsafe: {safety_diff.newly_unsafe.join(", ")}</p>
                )}
                {safety_diff.resolved.length > 0 && (
                  <p className="mt-0.5 text-success">Resolved: {safety_diff.resolved.join(", ")}</p>
                )}
              </div>
            )}

            {grounding_diff.changed && (
              <div>
                <p className="font-semibold tracking-wide text-ink-3 uppercase">Grounding</p>
                <p className="mt-1 text-ink-2">
                  {grounding_diff.baseline_status ?? "—"} → {grounding_diff.candidate_status ?? "—"}
                </p>
              </div>
            )}

            {(trial_summary.baseline_trial_verdicts.length > 0 ||
              trial_summary.candidate_trial_verdicts.length > 0) && (
              <div>
                <p className="font-semibold tracking-wide text-ink-3 uppercase">Trial verdicts</p>
                <p className="mt-1 text-ink-2">
                  Baseline: {trial_summary.baseline_trial_verdicts.join(", ") || "—"}
                </p>
                <p className="mt-0.5 text-ink-2">
                  Candidate: {trial_summary.candidate_trial_verdicts.join(", ") || "—"}
                </p>
              </div>
            )}
          </div>
        </details>
      )}
    </Card>
  );
}

export default function RegressionPage() {
  const { agentId, suiteId, suiteRunId } = useParams<{
    agentId: string;
    suiteId: string;
    suiteRunId: string;
  }>();
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  const regressionQuery = useQuery({
    queryKey: ["regression", suiteId, suiteRunId],
    queryFn: () => getRegression(suiteId, suiteRunId),
    enabled: checkedAuth,
    retry: false,
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

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const regression = regressionQuery.data;
  const caseNameById = new Map((casesQuery.data ?? []).map((c) => [c.id, c.name]));
  const versionLabelById = new Map((versionsQuery.data ?? []).map((v) => [v.id, v.label]));

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href={`/agents/${agentId}/test-suites/${suiteId}/runs/${suiteRunId}`}
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        Suite run
      </Link>
      <p className="text-sm font-semibold text-ink">Regression</p>
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-4xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Regression comparison</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          Candidate SuiteRun compared against the latest SuiteRun of the Agent Version currently
          marked as baseline.
        </p>

        {regressionQuery.isLoading && (
          <div className="mt-6 flex flex-col gap-3">
            <Skeleton className="h-20" />
            <Skeleton className="h-40" />
          </div>
        )}

        {regressionQuery.isError && (
          <p className="mt-6 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {regressionQuery.error instanceof ApiError
              ? regressionQuery.error.message
              : "Could not load the regression comparison."}
          </p>
        )}

        {regression && (
          <>
            <div className="mt-6 grid grid-cols-1 gap-3 text-xs text-ink-3 sm:grid-cols-2">
              <div>
                <p className="tracking-wide uppercase">Candidate</p>
                <p className="mt-0.5 text-ink-2">
                  {versionLabelById.get(regression.candidate_agent_version_id) ??
                    regression.candidate_agent_version_id}
                </p>
                <p className="mt-0.5 font-mono text-[11px] text-ink-3">{regression.candidate_suite_run_id}</p>
              </div>
              <div>
                <p className="tracking-wide uppercase">Baseline</p>
                <p className="mt-0.5 text-ink-2">
                  {versionLabelById.get(regression.baseline_agent_version_id) ??
                    regression.baseline_agent_version_id}
                </p>
                <p className="mt-0.5 font-mono text-[11px] text-ink-3">{regression.baseline_suite_run_id}</p>
              </div>
            </div>

            <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              <MetricCard label="Regressions" value={String(regression.summary.regressions)} tone="danger" />
              <MetricCard label="Improvements" value={String(regression.summary.improvements)} tone="success" />
              <MetricCard label="Unchanged" value={String(regression.summary.unchanged)} />
              <MetricCard label="Changed" value={String(regression.summary.changed)} tone="warning" />
              <MetricCard
                label="Baseline pass rate"
                value={formatRate(regression.summary.baseline_pass_rate)}
              />
              <MetricCard
                label="Candidate pass rate"
                value={formatRate(regression.summary.candidate_pass_rate)}
              />
              <MetricCard
                label="Pass rate delta"
                value={
                  regression.summary.pass_rate_delta !== null
                    ? `${regression.summary.pass_rate_delta >= 0 ? "+" : ""}${Math.round(
                        regression.summary.pass_rate_delta * 100,
                      )}%`
                    : "—"
                }
                tone={
                  regression.summary.pass_rate_delta === null
                    ? "neutral"
                    : regression.summary.pass_rate_delta < 0
                      ? "danger"
                      : regression.summary.pass_rate_delta > 0
                        ? "success"
                        : "neutral"
                }
              />
              <MetricCard label="New cases" value={String(regression.summary.new_cases)} />
              <MetricCard label="Missing cases" value={String(regression.summary.missing_cases)} />
              <MetricCard label="Safety changes" value={String(regression.summary.safety_changes)} />
              <MetricCard label="Grounding changes" value={String(regression.summary.grounding_changes)} />
              <MetricCard label="Latency changes" value={String(regression.summary.latency_changes)} />
              <MetricCard label="Tool changes" value={String(regression.summary.tool_changes)} />
            </div>

            <div className="mt-7">
              <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Case comparison</p>

              {regression.cases.length === 0 && (
                <div className="mt-3">
                  <EmptyState
                    icon={<VerifyIcon />}
                    title="No comparable cases"
                    description="No test cases were matched between the baseline and candidate suite runs."
                  />
                </div>
              )}

              {regression.cases.length > 0 && regression.summary.regressions === 0 && (
                <p className="mt-3 rounded-md border border-line bg-surface-2 px-3 py-2 text-sm text-ink-2">
                  No regressions detected — {regression.summary.improvements} improvement
                  {regression.summary.improvements === 1 ? "" : "s"}, {regression.summary.unchanged} unchanged,{" "}
                  {regression.summary.changed} changed.
                </p>
              )}

              <div className="mt-3 flex flex-col gap-3">
                {regression.cases.map((comparison) => (
                  <CaseRow
                    key={comparison.test_case_id}
                    comparison={comparison}
                    caseName={caseNameById.get(comparison.test_case_id) ?? comparison.test_case_id}
                  />
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
