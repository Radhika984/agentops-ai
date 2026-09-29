"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../../../../../../../../components/AppShell";
import { Badge, type Tone } from "../../../../../../../../components/ui/Badge";
import { Button } from "../../../../../../../../components/ui/Button";
import { Disclosure, LabeledCodeBlock } from "../../../../../../../../components/ui/CodeDisclosure";
import { Skeleton } from "../../../../../../../../components/ui/Skeleton";
import { ChevronLeftIcon, WarningIcon } from "../../../../../../../../components/ui/icons";
import {
  ApiError,
  AUTOFIX_OPTION_LABEL,
  clearToken,
  getRCA,
  getSuiteRunResult,
  listTestCases,
  proposeAutoFix,
  type EvaluationCheck,
  type RCAEvidenceItem,
  type RCATier,
  type TrialEntry,
  type Verdict,
} from "../../../../../../../../lib/api";
import { useRequireAuth } from "../../../../../../../../lib/useRequireAuth";

function verdictTone(verdict: Verdict): Tone {
  if (verdict === "PASS") return "success";
  if (verdict === "FAIL") return "danger";
  return "warning";
}

function checkTone(status: EvaluationCheck["status"]): Tone {
  if (status === "pass") return "success";
  if (status === "fail") return "danger";
  if (status === "skipped") return "neutral";
  return "warning"; // inconclusive, pending_llm
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function formatOutput(value: unknown): string {
  if (value === null || value === undefined) return "(no output)";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

/** The LLM Judge (Phase 19) persists its score/threshold only inside
 * this check's own metadata (backend/app/evaluation/checks/llm_judge.py)
 * — surfaced here, for check_type "rubric_judge" specifically, exactly
 * as returned; never recomputed or fabricated when absent. */
function CheckRow({ check }: { check: EvaluationCheck }) {
  const score = typeof check.metadata?.score === "number" ? check.metadata.score : null;
  const rubricThreshold =
    typeof check.metadata?.rubric_threshold === "number" ? check.metadata.rubric_threshold : null;

  return (
    <li className="rounded-md bg-surface px-2.5 py-2 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono font-medium text-ink">{check.check_type}</span>
        <span className="flex items-center gap-1.5">
          <span className="text-[10px] tracking-wide text-ink-3 uppercase">
            {check.determinism === "requires_llm" ? "requires LLM" : "deterministic"}
          </span>
          <Badge tone={checkTone(check.status)}>{check.status}</Badge>
        </span>
      </div>
      <p className="mt-1 whitespace-pre-wrap text-ink-2">{check.detail}</p>
      {(score !== null || rubricThreshold !== null) && (
        <p className="mt-1 text-[11px] text-ink-3">
          {score !== null && `Judge score: ${score.toFixed(2)}`}
          {score !== null && rubricThreshold !== null && " · "}
          {rubricThreshold !== null && `Threshold: ${rubricThreshold.toFixed(2)}`}
        </p>
      )}
    </li>
  );
}

function TrialCard({ trial }: { trial: TrialEntry }) {
  return (
    <Disclosure
      variant="row"
      summary={<span className="font-medium text-ink">Trial {trial.trial_index + 1}</span>}
      meta={
        <>
          {trial.llm_judge_invoked && <Badge tone="accent">LLM judge</Badge>}
          <Badge tone={verdictTone(trial.verdict)}>{trial.verdict}</Badge>
        </>
      }
    >
      <div className="flex flex-wrap gap-4 text-ink-3">
        <span>
          Status: <span className="text-ink-2">{trial.status}</span>
        </span>
        <span>
          Latency:{" "}
          <span className="text-ink-2">{trial.latency_ms !== null ? formatMs(trial.latency_ms) : "—"}</span>
        </span>
      </div>

      {trial.error && (
        <p className="flex items-center gap-1.5 rounded-md bg-danger-soft px-2.5 py-2 text-danger">
          <WarningIcon />
          {trial.error}
        </p>
      )}

      <LabeledCodeBlock label="Output" value={formatOutput(trial.actual_output)} />

      {trial.checks.length > 0 && (
        <div>
          <p className="font-semibold tracking-wide text-ink-3 uppercase">Checks</p>
          <ul className="mt-1 flex flex-col gap-1.5">
            {trial.checks.map((c, i) => (
              <CheckRow key={i} check={c} />
            ))}
          </ul>
        </div>
      )}
    </Disclosure>
  );
}

function tierTone(tier: RCATier): Tone {
  if (tier === "deterministic") return "success";
  if (tier === "llm_hypothesis") return "accent";
  if (tier === "insufficient_evidence") return "warning";
  return "neutral"; // not_applicable
}

function tierLabel(tier: RCATier): string {
  if (tier === "deterministic") return "Deterministic";
  if (tier === "llm_hypothesis") return "LLM hypothesis";
  if (tier === "insufficient_evidence") return "Insufficient evidence";
  return "Not applicable";
}

function EvidenceRow({ item }: { item: RCAEvidenceItem }) {
  return (
    <li className="rounded-md bg-surface px-2.5 py-2 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono font-medium text-ink">{item.check_type}</span>
        {item.status && <Badge tone={item.status === "fail" ? "danger" : "warning"}>{item.status}</Badge>}
      </div>
      <p className="mt-1 whitespace-pre-wrap text-ink-2">{item.detail}</p>
    </li>
  );
}

/** On-demand RCA — never auto-fetched on page load, since an unmatched
 * failure reaching the LLM-hypothesis tier makes a real model call
 * (backend/app/rca/service.py); only a click triggers
 * GET /suite-runs/{id}/results/{id}/rca. Nothing here computes a root
 * cause itself — every field is the backend's own response, rendered
 * as-is, with the LLM tier clearly labeled as a hypothesis. */
function RCAPanel({ suiteRunId, resultId }: { suiteRunId: string; resultId: string }) {
  const rcaMutation = useMutation({ mutationFn: () => getRCA(suiteRunId, resultId) });
  const rca = rcaMutation.data;

  return (
    <div className="border-t border-line px-4 py-3.5">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Root cause analysis</p>
        {!rca && (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => rcaMutation.mutate()}
            disabled={rcaMutation.isPending}
          >
            {rcaMutation.isPending ? "Analyzing…" : "Run root cause analysis"}
          </Button>
        )}
      </div>

      {rcaMutation.isError && (
        <p className="mt-2 rounded-md bg-danger-soft px-3 py-2 text-xs text-danger">
          {rcaMutation.error instanceof ApiError
            ? rcaMutation.error.message
            : "Could not analyze this result."}
        </p>
      )}

      {rca && (
        <div className="mt-2 flex flex-col gap-3 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={tierTone(rca.tier)}>{tierLabel(rca.tier)}</Badge>
            {rca.root_cause_category && <Badge tone="danger">{rca.root_cause_category}</Badge>}
          </div>

          {rca.tier === "llm_hypothesis" ? (
            <div className="rounded-md border border-accent/30 bg-accent-soft px-3 py-2">
              <p className="text-[10px] font-semibold tracking-wide text-accent uppercase">
                RCA hypothesis — not established fact
              </p>
              <p className="mt-1 whitespace-pre-wrap text-ink-2">{rca.explanation}</p>
            </div>
          ) : (
            <p className="whitespace-pre-wrap text-ink-2">{rca.explanation}</p>
          )}

          {rca.all_matched_categories.length > 1 && (
            <p className="text-ink-3">
              Other matched categories:{" "}
              {rca.all_matched_categories.filter((c) => c !== rca.root_cause_category).join(", ")}
            </p>
          )}

          {rca.evidence_references.length > 0 && (
            <div>
              <p className="font-semibold tracking-wide text-ink-3 uppercase">Evidence</p>
              <ul className="mt-1 flex flex-col gap-1.5">
                {rca.evidence_references.map((item, i) => (
                  <EvidenceRow key={i} item={item} />
                ))}
              </ul>
            </div>
          )}

          {rca.trace_span_ids.length > 0 && (
            <div>
              <p className="font-semibold tracking-wide text-ink-3 uppercase">Trace spans</p>
              <p className="mt-1 font-mono text-[11px] text-ink-2">{rca.trace_span_ids.join(", ")}</p>
            </div>
          )}

          {rca.regression && (
            <div>
              <p className="font-semibold tracking-wide text-ink-3 uppercase">Regression evidence</p>
              <p className="mt-1 text-ink-2">
                {rca.regression.baseline_verdict} → {rca.regression.candidate_verdict} (
                {rca.regression.classification})
              </p>
              <p className="mt-0.5 text-ink-3">
                Output changed: {String(rca.regression.output_changed)} · Tools changed:{" "}
                {String(rca.regression.tool_changed)} · Safety changed: {String(rca.regression.safety_changed)} ·
                Grounding changed: {String(rca.regression.grounding_changed)}
              </p>
            </div>
          )}

          <Button
            variant="tertiary"
            size="sm"
            onClick={() => rcaMutation.mutate()}
            disabled={rcaMutation.isPending}
            className="self-start"
          >
            {rcaMutation.isPending ? "Re-analyzing…" : "Re-run analysis"}
          </Button>
        </div>
      )}
    </div>
  );
}

/** On-demand AutoFix proposal — never auto-triggered. Calls the ONE
 * existing endpoint, POST .../autofix (backend/app/api/v1/autofix.py).
 * Options 1-3 (testcase_edit/agent_default_edit/trial_count_increase)
 * only ever create a pending Approval(node="auto_fix") here; applying it
 * happens exclusively through the existing Approvals page's
 * approve/reject flow — this panel never patches a TestCase, never
 * updates an Agent, and never touches AgentVersion.adapter_config itself.
 * Option 4 (owner_suggestion) writes TestCaseResult.suggested_fix
 * server-side with no approval — shown here as a clearly-labeled,
 * not-applied suggestion. */
function AutoFixPanel({ suiteRunId, resultId }: { suiteRunId: string; resultId: string }) {
  const queryClient = useQueryClient();
  const [preferAgentDefault, setPreferAgentDefault] = useState(false);

  const proposeMutation = useMutation({
    mutationFn: () => proposeAutoFix(suiteRunId, resultId, preferAgentDefault),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["suite-run-result", suiteRunId, resultId] });
    },
  });
  const proposal = proposeMutation.data;

  return (
    <div className="border-t border-line px-4 py-3.5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">AutoFix</p>
        {!proposal && (
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-[11px] text-ink-3">
              <input
                type="checkbox"
                checked={preferAgentDefault}
                onChange={(e) => setPreferAgentDefault(e.target.checked)}
                className="h-3.5 w-3.5 accent-accent rounded border-line-strong text-accent focus-visible:ring-4 focus-visible:ring-accent/10"
              />
              Prefer an agent-level fix (only applies to some failures)
            </label>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => proposeMutation.mutate()}
              disabled={proposeMutation.isPending}
            >
              {proposeMutation.isPending ? "Proposing…" : "Propose AutoFix"}
            </Button>
          </div>
        )}
      </div>

      {proposeMutation.isError && (
        <p className="mt-2 rounded-md bg-danger-soft px-3 py-2 text-xs text-danger">
          {proposeMutation.error instanceof ApiError
            ? proposeMutation.error.message
            : "Could not propose an AutoFix."}
        </p>
      )}

      {proposal && (
        <div className="mt-2 flex flex-col gap-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={proposal.requires_approval ? "warning" : "neutral"}>
              {AUTOFIX_OPTION_LABEL[proposal.option] ?? proposal.option}
            </Badge>
            {proposal.rca_category && <Badge tone="danger">{proposal.rca_category}</Badge>}
          </div>

          <p className="whitespace-pre-wrap text-ink-2">{proposal.rationale}</p>

          {proposal.field &&
            (proposal.current_value !== undefined || proposal.proposed_value !== undefined) && (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <LabeledCodeBlock label={`Current — ${proposal.field}`} value={proposal.current_value} />
                <LabeledCodeBlock label={`Proposed — ${proposal.field}`} value={proposal.proposed_value} />
              </div>
            )}

          {proposal.suggested_fix_recorded ? (
            <p className="rounded-md border border-line bg-surface-2 px-2.5 py-2 text-ink-2">
              <span className="font-semibold text-ink">Suggestion — not applied.</span> Recorded above
              under &ldquo;Suggested fix&rdquo;; nothing was changed automatically.
            </p>
          ) : (
            <p className="flex flex-wrap items-center gap-1.5 rounded-md bg-warning-soft px-2.5 py-2 text-warning">
              <WarningIcon />
              Approval required before this change is applied.{" "}
              <Link href="/approvals" className="underline">
                Review in the Approvals queue
              </Link>
              .
            </p>
          )}

          <Button
            variant="tertiary"
            size="sm"
            onClick={() => proposeMutation.mutate()}
            disabled={proposeMutation.isPending}
            className="self-start"
          >
            {proposeMutation.isPending ? "Proposing…" : "Propose again"}
          </Button>
        </div>
      )}
    </div>
  );
}

export default function TestCaseResultDetailPage() {
  const { agentId, suiteId, suiteRunId, resultId } = useParams<{
    agentId: string;
    suiteId: string;
    suiteRunId: string;
    resultId: string;
  }>();
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  const resultQuery = useQuery({
    queryKey: ["suite-run-result", suiteRunId, resultId],
    queryFn: () => getSuiteRunResult(suiteRunId, resultId),
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

  const result = resultQuery.data;
  const testCase = casesQuery.data?.find((c) => c.id === result?.test_case_id);

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href={`/agents/${agentId}/test-suites/${suiteId}/runs/${suiteRunId}`}
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        Suite run
      </Link>
      <p className="truncate text-sm font-semibold text-ink">{testCase?.name ?? "Test case result"}</p>
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-3xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">
          {testCase?.name ?? "Test case result"}
        </h1>

        {resultQuery.isLoading && (
          <div className="mt-6 flex flex-col gap-3">
            <Skeleton className="h-24" />
            <Skeleton className="h-40" />
          </div>
        )}

        {resultQuery.isError && (
          <p className="mt-6 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {resultQuery.error instanceof ApiError ? resultQuery.error.message : "Could not load this result."}
          </p>
        )}

        {result && (
          <div className="mt-6 overflow-hidden rounded-lg border border-line bg-surface-elevated shadow-md">
            <div className="grid grid-cols-2 gap-3 px-4 py-3.5 sm:grid-cols-4">
              <div>
                <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Verdict</p>
                <div className="mt-1">
                  <Badge tone={verdictTone(result.verdict)}>{result.verdict}</Badge>
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Method</p>
                <p className="mt-1 text-sm font-medium text-ink">{result.verdict_method}</p>
              </div>
              <div>
                <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Latency</p>
                <p className="mt-1 text-sm font-medium text-ink">
                  {result.latency_ms !== null ? formatMs(result.latency_ms) : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Trials</p>
                <p className="mt-1 text-sm font-medium text-ink">{result.trials.length}</p>
              </div>
            </div>

            {result.trials.length > 0 && (
              <p className="border-t border-line px-4 py-2.5 text-xs text-ink-3">
                The verdict above is aggregated from all {result.trials.length} trial
                {result.trials.length === 1 ? "" : "s"} below via &ldquo;{result.verdict_method}&rdquo; — shown
                exactly as returned, never recalculated here.
              </p>
            )}

            {result.error && (
              <div className="border-t border-line px-4 py-3.5">
                <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Error</p>
                <p className="mt-2 flex items-center gap-1.5 rounded-md bg-danger-soft px-2.5 py-2 text-xs text-danger">
                  <WarningIcon />
                  {result.error}
                </p>
              </div>
            )}

            <div className="border-t border-line px-4 py-3.5">
              <LabeledCodeBlock label="Actual output" value={formatOutput(result.actual_output)} />
            </div>

            {result.suggested_fix && (
              <div className="border-t border-line px-4 py-3.5">
                <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Suggested fix</p>
                <p className="mt-2 whitespace-pre-wrap text-sm text-ink-2">{result.suggested_fix}</p>
              </div>
            )}

            <div className="border-t border-line px-4 py-3.5">
              <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Checks</p>
              {result.checks.length === 0 ? (
                <p className="mt-2 text-xs text-ink-3">No checks were applicable to this result.</p>
              ) : (
                <ul className="mt-2 flex flex-col gap-1.5">
                  {result.checks.map((check, i) => (
                    <CheckRow key={i} check={check} />
                  ))}
                </ul>
              )}
            </div>

            <RCAPanel suiteRunId={suiteRunId} resultId={resultId} />

            <AutoFixPanel suiteRunId={suiteRunId} resultId={resultId} />

            {result.trials.length > 0 && (
              <div className="border-t border-line px-4 py-3.5">
                <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Trials</p>
                <div className="mt-2 flex flex-col gap-2">
                  {result.trials.map((trial) => (
                    <TrialCard key={trial.trial_index} trial={trial} />
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
