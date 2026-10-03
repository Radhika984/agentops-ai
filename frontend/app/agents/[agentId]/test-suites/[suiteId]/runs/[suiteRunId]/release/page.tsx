"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AppShell } from "../../../../../../../components/AppShell";
import { Badge } from "../../../../../../../components/ui/Badge";
import { Button } from "../../../../../../../components/ui/Button";
import { Card } from "../../../../../../../components/ui/Card";
import { Disclosure } from "../../../../../../../components/ui/CodeDisclosure";
import { ChevronLeftIcon, WarningIcon } from "../../../../../../../components/ui/icons";
import { STATUS_META, StatusBadge, type StatusKey } from "../../../../../../../components/ui/Status";
import {
  ApiError,
  clearToken,
  evaluateRelease,
  getSuiteRun,
  listAgentVersions,
  listApprovals,
  listTestCases,
  type HardGateReasonRead,
} from "../../../../../../../lib/api";
import { useRequireAuth } from "../../../../../../../lib/useRequireAuth";

function formatRate(rate: number | null): string {
  return rate === null ? "—" : `${Math.round(rate * 100)}%`;
}

function formatTimestamp(value: string | null | undefined): string {
  return value ? new Date(value).toLocaleString() : "—";
}

// The backend's five real, deterministic hard-gate categories
// (backend/app/release_gate/gate.py's own HARD_GATE_CATEGORIES) — nothing
// invented. Only four of these five get a dedicated `*_count` field on
// ReleaseDecisionResponse (safety_flag/forbidden_tool/missing_required_
// tool/schema_failure) — correctness_failure has no matching count field,
// but its reasons are still present in `hard_gate_reasons`, so it still
// needs its own row here or those failures silently disappear from the
// page even though they're real hard-gate blockers.
const HARD_GATE_ROWS: { category: string; label: string }[] = [
  { category: "safety_flag", label: "Safety" },
  { category: "forbidden_tool_called", label: "Forbidden tool calls" },
  { category: "missing_required_tool_call", label: "Missing required tools" },
  { category: "schema_failure", label: "Schema failures" },
  { category: "correctness_failure", label: "Correctness failures" },
];

function HardGateReasonRow({ reason, caseName }: { reason: HardGateReasonRead; caseName: string }) {
  return (
    <li className="rounded-control bg-surface px-2.5 py-2 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium text-ink">{caseName}</span>
        <span className="font-mono text-[11px] text-ink-3">{reason.check_type}</span>
      </div>
      <p className="mt-0.5 whitespace-pre-wrap text-ink-2">{reason.detail}</p>
    </li>
  );
}

/** One hard-gate row — a plain PASS row when the category has zero
 * reasons, an expandable FAIL row (real failing cases, not a count
 * alone) when it doesn't. */
function HardGateRow({
  label,
  reasons,
  caseNameById,
}: {
  label: string;
  reasons: HardGateReasonRead[];
  caseNameById: Map<string, string>;
}) {
  const count = reasons.length;
  if (count === 0) {
    return (
      <div className="flex items-center justify-between gap-2 px-4 py-3">
        <span className="flex items-center gap-2 text-sm text-ink">
          <StatusBadge status="PASS" />
          {label}
        </span>
        <span className="text-xs text-ink-3 tabular-nums">0 cases</span>
      </div>
    );
  }
  return (
    <Disclosure
      variant="row"
      summary={
        <span className="flex items-center gap-2 text-sm text-ink">
          <StatusBadge status="FAIL" />
          {label}
        </span>
      }
      meta={<span className="tabular-nums text-xs text-ink-3">{count} case{count === 1 ? "" : "s"}</span>}
    >
      <ul className="flex flex-col gap-1.5">
        {reasons.map((reason, i) => (
          <HardGateReasonRow key={i} reason={reason} caseName={caseNameById.get(reason.test_case_id) ?? reason.test_case_id} />
        ))}
      </ul>
    </Disclosure>
  );
}

function SoftStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-line py-2 text-sm last:border-b-0">
      <dt className="text-ink-3">{label}</dt>
      <dd className="font-medium text-ink tabular-nums">{value}</dd>
    </div>
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

  // Real fields for the verdict band's "candidate vs baseline version"
  // and "suite run + timestamp" — this page previously showed neither,
  // since evaluateRelease()'s own response has no agent_version_id.
  const suiteRunQuery = useQuery({
    queryKey: ["suite-run", suiteRunId],
    queryFn: () => getSuiteRun(suiteRunId),
    enabled: checkedAuth,
  });

  const versionsQuery = useQuery({
    queryKey: ["agent-versions", agentId],
    queryFn: () => listAgentVersions(agentId),
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
  const releaseApprovalStatus: StatusKey | null = releaseApproval
    ? ({ pending: "PENDING", approved: "APPROVED", rejected: "REJECTED" } as const)[releaseApproval.status]
    : null;

  const candidateVersion = versionsQuery.data?.find((v) => v.id === suiteRunQuery.data?.agent_version_id);
  const baselineVersion = versionsQuery.data?.find((v) => v.is_baseline);
  const hasDistinctBaseline = baselineVersion && baselineVersion.id !== candidateVersion?.id;

  const statusKey: StatusKey | null = release ? (release.decision === "pass" ? "PASS" : "HOLD") : null;
  const statusMeta = statusKey ? STATUS_META[statusKey] : null;

  const regressionHref = `/agents/${agentId}/test-suites/${suiteId}/runs/${suiteRunId}/regression`;
  const suiteRunHref = `/agents/${agentId}/test-suites/${suiteId}/runs/${suiteRunId}`;

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href={suiteRunHref}
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
        <h1 className="text-page-title">Release review</h1>
        <p className="mt-1.5 text-body">
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
              <p className="mt-3 rounded-control bg-danger-soft px-3 py-2 text-sm text-danger">
                {releaseMutation.error instanceof ApiError
                  ? releaseMutation.error.message
                  : "Could not evaluate the release gate."}
              </p>
            )}
          </div>
        )}

        {release && statusMeta && (
          <>
            {/* Verdict band — the one place in the app besides the Home
                hero that uses the serif display face, per the design
                brief: this is the single most important decision on the
                page, so it gets the app's one other headline moment. */}
            <div className={`animate-fade-in mt-6 rounded-surface px-5 py-5 ${statusMeta.tone === "success" ? "bg-success-soft" : "bg-danger-soft"}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex items-center gap-3">
                  <statusMeta.icon className={statusMeta.tone === "success" ? "text-success" : "text-danger"} />
                  <h2
                    className={`font-serif text-3xl ${statusMeta.tone === "success" ? "text-success" : "text-danger"}`}
                  >
                    {statusMeta.label}
                  </h2>
                </div>
                <Button
                  variant="tertiary"
                  size="sm"
                  onClick={() => releaseMutation.mutate()}
                  disabled={releaseMutation.isPending}
                >
                  {releaseMutation.isPending ? "Re-evaluating…" : "Re-evaluate"}
                </Button>
              </div>
              <p className={`mt-2 text-sm ${statusMeta.tone === "success" ? "text-success" : "text-danger"}`}>
                {release.reason}
              </p>
              <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1.5 border-t border-current/15 pt-3 text-xs">
                <span className="flex items-center gap-1.5 text-ink-2">
                  Version
                  <code className="font-mono text-ink">{candidateVersion?.label ?? suiteRunQuery.data?.agent_version_id ?? "—"}</code>
                  {candidateVersion?.is_baseline && <Badge tone="accent">baseline</Badge>}
                </span>
                {hasDistinctBaseline && (
                  <span className="flex items-center gap-1.5 text-ink-2">
                    Baseline
                    <code className="font-mono text-ink">{baselineVersion!.label}</code>
                  </span>
                )}
                <span className="flex items-center gap-1.5 text-ink-2">
                  Suite run
                  <Link href={suiteRunHref} className="font-mono text-accent hover:underline">
                    {suiteRunId}
                  </Link>
                </span>
                <span className="text-ink-2">
                  {formatTimestamp(suiteRunQuery.data?.completed_at ?? suiteRunQuery.data?.created_at)}
                </span>
              </div>
            </div>

            {release.approval_required && (
              <div className="mt-3 rounded-control bg-accent-soft px-3 py-2 text-sm text-accent">
                <p className="flex flex-wrap items-center gap-1.5">
                  <WarningIcon />
                  Human approval is required before this SuiteRun is actually released.{" "}
                  <Link href="/approvals" className="underline">
                    Review in the Approvals queue
                  </Link>
                  .
                </p>
                {approvalsQuery.isLoading && <p className="mt-1.5 text-xs">Checking approval status…</p>}
                {releaseApprovalStatus && (
                  <p className="mt-1.5 flex items-center gap-1.5 text-xs">
                    Current status:
                    <StatusBadge status={releaseApprovalStatus} />
                  </p>
                )}
              </div>
            )}

            {/* Hard gates — deterministic, dividers not cards; each row
                expands to the real failing cases, never just a count. */}
            <div className="mt-7 overflow-hidden rounded-surface border border-line">
              <div className="border-b border-line bg-surface-2 px-4 py-3">
                <p className="text-section-title">Hard gates</p>
                <p className="mt-0.5 text-body-muted">Deterministic — any failure blocks release.</p>
              </div>
              <div className="flex flex-col divide-y divide-line">
                {HARD_GATE_ROWS.map((row) => (
                  <HardGateRow
                    key={row.category}
                    label={row.label}
                    reasons={release.hard_gate_reasons.filter((r) => r.category === row.category)}
                    caseNameById={caseNameById}
                  />
                ))}
              </div>
            </div>

            {/* Soft signals — visibly quieter (no colored band, no
                dividers-with-icons treatment), explicitly labeled
                advisory so a reader can never mistake it for a gate. */}
            <div className="mt-5 rounded-surface border border-line">
              <div className="border-b border-line px-4 py-3">
                <p className="text-section-title">Soft signals</p>
                <p className="mt-0.5 text-body-muted">
                  Score-based — informs the decision, does not block release on its own.
                </p>
              </div>
              <div className="px-4 py-4">
                <dl className="flex flex-col">
                  <SoftStat label="Total cases" value={String(release.total_cases)} />
                  <SoftStat label="Pass rate" value={formatRate(release.pass_rate)} />
                  <SoftStat label="Inconclusive rate" value={formatRate(release.inconclusive_rate)} />
                  <SoftStat label="Soft score" value={release.soft_score.toFixed(2)} />
                </dl>

                {Object.keys(release.soft_score_components).length > 0 && (
                  <Card className="mt-3" elevation="flat">
                    <p className="text-metric-label">Score components</p>
                    <dl className="mt-2 flex flex-col gap-1 text-xs">
                      {Object.entries(release.soft_score_components).map(([key, value]) => (
                        <div key={key} className="flex items-center justify-between">
                          <dt className="text-ink-3">{key}</dt>
                          <dd className="font-mono text-ink-2 tabular-nums">{value.toFixed(3)}</dd>
                        </div>
                      ))}
                    </dl>
                  </Card>
                )}

                <p className="mt-3 text-body-muted">
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
                      . <Link href={regressionHref} className="text-accent hover:underline">View regression comparison</Link>
                    </>
                  ) : (
                    "No baseline regression comparison was available as a soft-score input."
                  )}
                </p>

                {release.rubric_case_count > 0 && (
                  <p className="mt-2 rounded-control border border-line bg-surface-2 px-3 py-2 text-body-muted">
                    {release.rubric_case_count} rubric (subjective) case{release.rubric_case_count === 1 ? "" : "s"} —
                    excluded from the hard gate.
                  </p>
                )}
              </div>
            </div>

            {/* Audit trail — every input this decision was reconstructed
                from, so it's traceable after the fact. */}
            <div className="mt-5">
              <p className="text-section-title">Audit trail</p>
              <ul className="mt-2 flex flex-col gap-1.5 text-sm text-ink-2">
                <li>
                  Suite run <Link href={suiteRunHref} className="font-mono text-accent hover:underline">{suiteRunId}</Link>
                  {" "}— {release.total_cases} case{release.total_cases === 1 ? "" : "s"} evaluated.
                </li>
                <li>
                  Regression comparison —{" "}
                  {release.regression.available ? (
                    <Link href={regressionHref} className="text-accent hover:underline">view comparison</Link>
                  ) : (
                    <span className="text-ink-3">not available for this run</span>
                  )}
                  .
                </li>
                <li>
                  Release approval —{" "}
                  {release.approval_required ? (
                    <>
                      <Link href="/approvals" className="text-accent hover:underline">Approvals queue</Link>
                      {releaseApprovalStatus && <> (<StatusBadge status={releaseApprovalStatus} />)</>}
                    </>
                  ) : (
                    <span className="text-ink-3">not required for a HOLD decision</span>
                  )}
                  .
                </li>
              </ul>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
