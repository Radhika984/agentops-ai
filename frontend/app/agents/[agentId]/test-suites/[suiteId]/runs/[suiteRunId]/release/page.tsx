"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AppShell } from "../../../../../../../components/AppShell";
import { Badge } from "../../../../../../../components/ui/Badge";
import { Button } from "../../../../../../../components/ui/Button";
import { Card } from "../../../../../../../components/ui/Card";
import { CheckIcon, ChevronLeftIcon, CloseIcon, WarningIcon } from "../../../../../../../components/ui/icons";
import { MetricCard } from "../../../../../../../components/ui/MetricCard";
import { VerdictBanner } from "../../../../../../../components/ui/VerdictBanner";
import {
  ApiError,
  clearToken,
  evaluateRelease,
  listApprovals,
  listTestCases,
  type HardGateReasonRead,
} from "../../../../../../../lib/api";
import { useRequireAuth } from "../../../../../../../lib/useRequireAuth";

function formatRate(rate: number | null): string {
  return rate === null ? "—" : `${Math.round(rate * 100)}%`;
}

// Matches approvals/page.tsx's own STATUS_TONE vocabulary exactly — the
// same status shown there, not a second color scheme for this page.
const APPROVAL_STATUS_TONE = { pending: "warning", approved: "success", rejected: "danger" } as const;

function HardGateReasonRow({ reason, caseName }: { reason: HardGateReasonRead; caseName: string }) {
  return (
    <li className="rounded-md bg-surface px-2.5 py-2 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-ink">{caseName}</span>
        <Badge tone="danger">{reason.category}</Badge>
      </div>
      <p className="mt-1 font-mono text-[11px] text-ink-3">{reason.check_type}</p>
      <p className="mt-0.5 whitespace-pre-wrap text-ink-2">{reason.detail}</p>
    </li>
  );
}

export default function ReleaseGatePage() {
  const { agentId, suiteId, suiteRunId } = useParams<{
    agentId: string;
    suiteId: string;
    suiteRunId: string;
  }>();
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  const casesQuery = useQuery({
    queryKey: ["test-cases", suiteId],
    queryFn: () => listTestCases(suiteId),
    enabled: checkedAuth,
  });

  const releaseMutation = useMutation({
    mutationFn: () => evaluateRelease(suiteRunId),
  });

  // Only fetched once approval is actually required — the release-gate
  // evaluation itself idempotently ensures the pending Approval row
  // exists (backend/app/services/release_gate_service.py), so this is
  // read-only: it shows that real row's real status, never claims
  // "approved" on its own.
  const approvalsQuery = useQuery({
    queryKey: ["approvals-for-release", suiteRunId],
    queryFn: () => listApprovals(),
    enabled: checkedAuth && releaseMutation.data?.approval_required === true,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const release = releaseMutation.data;
  const caseNameById = new Map((casesQuery.data ?? []).map((c) => [c.id, c.name]));
  const releaseApproval = approvalsQuery.data?.find(
    (a) => a.node === "release_decision" && a.suite_run_id === suiteRunId,
  );

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href={`/agents/${agentId}/test-suites/${suiteId}/runs/${suiteRunId}`}
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        Suite run
      </Link>
      <p className="text-sm font-semibold text-ink">Release review</p>
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-3xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Release review</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          Evaluates this SuiteRun&apos;s deterministic hard gate and soft score. Nothing here is
          computed in the browser — this runs the backend&apos;s release gate and shows its response
          exactly.
        </p>

        {!release && (
          <div className="mt-6">
            <Button variant="primary" onClick={() => releaseMutation.mutate()} disabled={releaseMutation.isPending}>
              {releaseMutation.isPending ? "Evaluating…" : "Run release gate evaluation"}
            </Button>
            {releaseMutation.isError && (
              <p className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                {releaseMutation.error instanceof ApiError
                  ? releaseMutation.error.message
                  : "Could not evaluate the release gate."}
              </p>
            )}
          </div>
        )}

        {release && (
          <>
            {/* Three real, distinct outcomes — not two: "pass" is always
                success, but a "hold" means something different depending
                on *why*. A hard-gate failure (safety/forbidden-tool/
                missing-tool/schema) is a deterministic block, shown as
                danger; a hold driven purely by the soft score (hard gate
                itself passed) is a softer "needs review" signal, shown as
                warning — using hard_gate_passed, a field this page
                already fetches and displays below, not a new one. Uses
                the shared VerdictBanner — the same "one loud moment"
                treatment as Suite Run and Result detail, not a
                page-local pill. */}
            <p className="mt-6 text-xs font-semibold tracking-wide text-ink-3 uppercase">
              Can this version be released?
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <VerdictBanner
                className="flex-1"
                tone={release.decision === "pass" ? "success" : release.hard_gate_passed ? "warning" : "danger"}
                icon={
                  release.decision === "pass" ? (
                    <CheckIcon />
                  ) : release.hard_gate_passed ? (
                    <WarningIcon />
                  ) : (
                    <CloseIcon />
                  )
                }
                headline={
                  release.decision === "pass"
                    ? "PASS — ready to release"
                    : release.hard_gate_passed
                      ? "HOLD — soft score below threshold"
                      : "HOLD — hard gate failed"
                }
                reason={release.reason}
              />
              <Button
                variant="tertiary"
                size="sm"
                onClick={() => releaseMutation.mutate()}
                disabled={releaseMutation.isPending}
              >
                {releaseMutation.isPending ? "Re-evaluating…" : "Re-evaluate"}
              </Button>
            </div>

            {release.approval_required && (
              <div className="mt-3 rounded-md bg-warning-soft px-3 py-2 text-sm text-warning">
                <p className="flex flex-wrap items-center gap-1.5">
                  <WarningIcon />
                  Human approval is required before this SuiteRun is actually released.{" "}
                  <Link href="/approvals" className="underline">
                    Review in the Approvals queue
                  </Link>
                  .
                </p>
                {approvalsQuery.isLoading && <p className="mt-1.5 text-xs">Checking approval status…</p>}
                {releaseApproval && (
                  <p className="mt-1.5 flex items-center gap-1.5 text-xs">
                    Current status:
                    <Badge tone={APPROVAL_STATUS_TONE[releaseApproval.status]}>{releaseApproval.status}</Badge>
                  </p>
                )}
              </div>
            )}

            {/* Two structurally separate zones, not two sequential
                sections that happen to have headers: a hard-gate failure
                is a deterministic block, a soft signal never is — §30's
                own requirement that it be "structurally impossible" to
                read a soft signal (latency, score) as blocking. The
                left-edge accent bar and independent Card surface are
                what make the split read as two zones, not just two
                headings on one page. */}
            <div className="mt-7 overflow-hidden rounded-lg border border-line">
              <div className="relative border-b border-line bg-danger-soft/40 px-4 py-3">
                <span className="absolute top-0 left-0 h-full w-1 bg-danger" aria-hidden="true" />
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold tracking-wide text-ink uppercase">Hard gates</p>
                    <p className="mt-0.5 text-xs text-ink-3">Deterministic — any failure blocks release.</p>
                  </div>
                  <Badge tone={release.hard_gate_passed ? "success" : "danger"}>
                    {release.hard_gate_passed ? "passed" : "failed"}
                  </Badge>
                </div>
              </div>
              <div className="px-4 py-4">
                {release.hard_gate_reasons.length === 0 ? (
                  <p className="text-xs text-ink-3">No hard-gate failures.</p>
                ) : (
                  <ul className="flex flex-col gap-1.5">
                    {release.hard_gate_reasons.map((reason, i) => (
                      <HardGateReasonRow
                        key={i}
                        reason={reason}
                        caseName={caseNameById.get(reason.test_case_id) ?? reason.test_case_id}
                      />
                    ))}
                  </ul>
                )}

                <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <MetricCard label="Safety flags" value={String(release.safety_flag_count)} tone={release.safety_flag_count > 0 ? "danger" : "neutral"} />
                  <MetricCard label="Forbidden tool calls" value={String(release.forbidden_tool_count)} tone={release.forbidden_tool_count > 0 ? "danger" : "neutral"} />
                  <MetricCard label="Missing required tools" value={String(release.missing_required_tool_count)} tone={release.missing_required_tool_count > 0 ? "danger" : "neutral"} />
                  <MetricCard label="Schema failures" value={String(release.schema_failure_count)} tone={release.schema_failure_count > 0 ? "danger" : "neutral"} />
                </div>
              </div>
            </div>

            <div className="mt-5 overflow-hidden rounded-lg border border-line">
              <div className="relative border-b border-line bg-surface-2 px-4 py-3">
                <span className="absolute top-0 left-0 h-full w-1 bg-line-strong" aria-hidden="true" />
                <p className="text-xs font-semibold tracking-wide text-ink uppercase">Soft signals</p>
                <p className="mt-0.5 text-xs text-ink-3">
                  Score-based — informs the decision, never blocks it on its own.
                </p>
              </div>
              <div className="px-4 py-4">
                <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Case counts</p>
                <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3">
                  <MetricCard label="Total" value={String(release.total_cases)} />
                  <MetricCard label="Pass" value={String(release.pass_count)} tone="success" />
                  <MetricCard label="Fail" value={String(release.fail_count)} tone="danger" />
                  <MetricCard label="Inconclusive" value={String(release.inconclusive_count)} tone="warning" />
                  <MetricCard label="Pass rate" value={formatRate(release.pass_rate)} />
                  <MetricCard label="Inconclusive rate" value={formatRate(release.inconclusive_rate)} />
                </div>

                <p className="mt-5 text-xs font-semibold tracking-wide text-ink-3 uppercase">Soft score</p>
                <Card className="mt-2" elevation="raised">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-ink">Score</span>
                    <span className="text-2xl font-bold tracking-tight text-ink">{release.soft_score.toFixed(2)}</span>
                  </div>
                  {Object.keys(release.soft_score_components).length > 0 && (
                    <dl className="mt-3 flex flex-col gap-1 border-t border-line pt-3 text-xs">
                      {Object.entries(release.soft_score_components).map(([key, value]) => (
                        <div key={key} className="flex items-center justify-between">
                          <dt className="text-ink-3">{key}</dt>
                          <dd className="font-mono text-ink-2">{value.toFixed(3)}</dd>
                        </div>
                      ))}
                    </dl>
                  )}
                </Card>

                <p className="mt-3 text-xs text-ink-3">
                  {release.regression.available ? (
                    <>
                      Regression input: {release.regression.regression_count} regression
                      {release.regression.regression_count === 1 ? "" : "s"},{" "}
                      {release.regression.improvement_count} improvement
                      {release.regression.improvement_count === 1 ? "" : "s"}
                      {release.regression.pass_rate_delta !== null &&
                        `, pass rate delta ${release.regression.pass_rate_delta >= 0 ? "+" : ""}${Math.round(
                          release.regression.pass_rate_delta * 100,
                        )}%`}
                      .
                    </>
                  ) : (
                    "No baseline regression comparison was available as a soft-score input."
                  )}
                </p>

                {release.rubric_case_count > 0 && (
                  <p className="mt-2 rounded-md border border-line bg-surface-2 px-3 py-2 text-xs text-ink-2">
                    {release.rubric_case_count} rubric (subjective) case{release.rubric_case_count === 1 ? "" : "s"} —
                    excluded from the hard gate.
                  </p>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
