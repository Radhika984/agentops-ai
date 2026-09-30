"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../../../../components/AppShell";
import { Badge, type Tone } from "../../../../components/ui/Badge";
import { Button } from "../../../../components/ui/Button";
import { CodeBlock, Disclosure, LabeledCodeBlock } from "../../../../components/ui/CodeDisclosure";
import { FlowSteps, type FlowStep } from "../../../../components/ui/FlowSteps";
import { Field } from "../../../../components/ui/Input";
import { Section } from "../../../../components/ui/Section";
import { Skeleton } from "../../../../components/ui/Skeleton";
import { CheckIcon, ChevronLeftIcon, WarningIcon } from "../../../../components/ui/icons";
import {
  ApiError,
  acceptCandidateTestCase,
  clearToken,
  createRegressionCandidate,
  getExecution,
  type EvaluationCheck,
  type ExecutionVerdict,
  type ProductionToolCallRecord,
  type TestCaseRead,
} from "../../../../lib/api";
import { useRequireAuth } from "../../../../lib/useRequireAuth";

function verdictTone(verdict: ExecutionVerdict): Tone {
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

/** One expandable tool-call row — the same INPUT/OUTPUT disclosure
 * pattern the legacy Run trace already uses (see RunAgentPanel.tsx's
 * ToolCallRow), adapted for a production execution's own reported call
 * shape (duration_ms optional here). */
function ToolCallRow({ tc }: { tc: ProductionToolCallRecord }) {
  return (
    <Disclosure
      variant="row"
      summary={<span className="font-mono font-medium text-ink">{tc.tool_name}</span>}
      meta={
        <>
          <Badge tone={tc.ok ? "success" : "danger"}>{tc.ok ? "ok" : "failed"}</Badge>
          {tc.duration_ms !== null && <span className="text-ink-3">{tc.duration_ms}ms</span>}
        </>
      }
    >
      <LabeledCodeBlock label="Input" value={tc.input} />
      {tc.output && <LabeledCodeBlock label="Output" value={tc.output} />}
    </Disclosure>
  );
}

function CheckRow({ check }: { check: EvaluationCheck }) {
  return (
    <li className="rounded-md bg-surface px-2.5 py-2 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono font-medium text-ink">{check.check_type}</span>
        <Badge tone={checkTone(check.status)}>{check.status}</Badge>
      </div>
      <p className="mt-1 whitespace-pre-wrap text-ink-2">{check.detail}</p>
    </li>
  );
}

/** The "Create Regression Candidate" form + its own success state — once
 * the API returns the created candidate TestCase, this shows exactly
 * what it contains and, if it's still `status: "candidate"`, an "Accept
 * Candidate" action that calls the real accept endpoint. Nothing here
 * runs or auto-accepts the candidate. */
function RegressionCandidatePanel({ executionId }: { executionId: string }) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [suiteId, setSuiteId] = useState("");
  const [name, setName] = useState("");
  const [expectedOutput, setExpectedOutput] = useState("");
  const [candidate, setCandidate] = useState<TestCaseRead | null>(null);

  const createMutation = useMutation({
    mutationFn: () =>
      createRegressionCandidate(executionId, {
        suite_id: suiteId.trim(),
        name: name.trim() || undefined,
        expected_output: expectedOutput.trim() || undefined,
      }),
    onSuccess: (created) => {
      setCandidate(created);
    },
  });

  const acceptMutation = useMutation({
    mutationFn: () => acceptCandidateTestCase(candidate!.id),
    onSuccess: (accepted) => {
      setCandidate(accepted);
      queryClient.invalidateQueries({ queryKey: ["test-cases", accepted.suite_id] });
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!suiteId.trim() || !expectedOutput.trim()) return;
    createMutation.mutate();
  }

  // PRODUCTION EXECUTION → ISSUE → REGRESSION CANDIDATE → SUITE (§31,
  // reduced from the brief's 5-step model to the states this page can
  // actually observe — there is no live "verification" signal to show
  // back on this execution once a candidate is later run in a suite).
  const flowSteps: FlowStep[] = [
    { label: "Production execution", tone: "neutral" },
    { label: "Issue detected", tone: "danger" },
    candidate
      ? { label: "Regression candidate created", tone: "accent" }
      : { label: "Regression candidate", tone: "neutral", pulse: true },
    candidate && candidate.status !== "candidate"
      ? { label: "Accepted — active in Suite Runner", tone: "success" }
      : { label: "Suite (pending acceptance)", tone: "neutral" },
  ];

  if (candidate) {
    const isCandidate = candidate.status === "candidate";
    return (
      <div className="flex flex-col gap-3">
        <FlowSteps steps={flowSteps} />
        <div className="rounded-lg border border-line bg-surface p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-medium text-ink">{candidate.name}</p>
          <Badge tone={isCandidate ? "warning" : "success"}>{candidate.status}</Badge>
        </div>
        <dl className="mt-2 flex flex-col gap-1 text-xs text-ink-2">
          <div>
            <dt className="inline font-medium text-ink-3">Test case ID: </dt>
            <dd className="inline font-mono">{candidate.id}</dd>
          </div>
          <div>
            <dt className="inline font-medium text-ink-3">Input: </dt>
            <dd className="inline">{JSON.stringify(candidate.input)}</dd>
          </div>
          {candidate.expected_output && (
            <div>
              <dt className="inline font-medium text-ink-3">Expected output: </dt>
              <dd className="inline">{candidate.expected_output}</dd>
            </div>
          )}
        </dl>

        {isCandidate ? (
          <div className="mt-3 border-t border-line pt-3">
            <Button
              variant="success"
              size="sm"
              onClick={() => acceptMutation.mutate()}
              disabled={acceptMutation.isPending}
            >
              <CheckIcon />
              {acceptMutation.isPending ? "Accepting…" : "Accept candidate"}
            </Button>
            <p className="mt-1.5 text-[11px] text-ink-3">
              Stays out of Suite Runner execution until accepted. Accepting does not run it.
            </p>
            {acceptMutation.isError && (
              <p className="mt-1.5 text-xs text-danger">
                {acceptMutation.error instanceof ApiError
                  ? acceptMutation.error.message
                  : "Could not accept the candidate."}
              </p>
            )}
          </div>
        ) : (
          <p className="mt-3 border-t border-line pt-3 text-xs font-medium text-success">
            <CheckIcon className="mr-1 inline" />
            Active — included in future Suite Runner executions.
          </p>
        )}
        </div>
      </div>
    );
  }

  if (!open) {
    return (
      <div className="flex flex-col gap-3">
        <FlowSteps steps={flowSteps} />
        <Button variant="secondary" size="sm" onClick={() => setOpen(true)} className="self-start">
          Create regression candidate
        </Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <FlowSteps steps={flowSteps} />
      <form onSubmit={handleSubmit} className="flex flex-col gap-2.5 rounded-lg border border-line bg-surface p-3">
      <Field
        label="Test suite ID"
        value={suiteId}
        onChange={(e) => setSuiteId(e.target.value)}
        placeholder="Suite this candidate belongs to"
        className="font-mono"
        required
      />
      <Field
        label="Name (optional)"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Regression: …"
      />
      <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
        Expected output
        <textarea
          value={expectedOutput}
          onChange={(e) => setExpectedOutput(e.target.value)}
          placeholder="What the agent should have produced"
          rows={3}
          required
          className="w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3 transition-colors duration-150 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/10"
        />
      </label>
      <div className="flex gap-2">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={createMutation.isPending || !suiteId.trim() || !expectedOutput.trim()}
        >
          {createMutation.isPending ? "Creating…" : "Create candidate"}
        </Button>
        <Button type="button" variant="tertiary" size="sm" onClick={() => setOpen(false)}>
          Cancel
        </Button>
      </div>
      {createMutation.isError && (
        <p className="text-xs text-danger">
          {createMutation.error instanceof ApiError
            ? createMutation.error.message
            : "Could not create the regression candidate."}
        </p>
      )}
      </form>
    </div>
  );
}

export default function ExecutionDetailPage() {
  const { versionId, executionId } = useParams<{ versionId: string; executionId: string }>();
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  const executionQuery = useQuery({
    queryKey: ["execution", versionId, executionId],
    queryFn: () => getExecution(versionId, executionId),
    enabled: checkedAuth,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const execution = executionQuery.data;

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href={`/agent-versions/${versionId}/monitoring`}
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        Monitoring
      </Link>
      <p className="truncate font-mono text-sm font-semibold text-ink">{executionId}</p>
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-3xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Execution detail</h1>

        {executionQuery.isLoading && (
          <div className="mt-6 flex flex-col gap-3">
            <Skeleton className="h-24" />
            <Skeleton className="h-40" />
          </div>
        )}

        {executionQuery.isError && (
          <p className="mt-6 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {executionQuery.error instanceof ApiError
              ? executionQuery.error.message
              : "Could not load this execution."}
          </p>
        )}

        {execution && (
          <div className="mt-6 overflow-hidden rounded-lg border border-line bg-surface-elevated shadow-md">
            <div className="grid grid-cols-2 gap-3 px-4 py-3.5 sm:grid-cols-4">
              <div>
                <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Verdict</p>
                <div className="mt-1">
                  <Badge tone={verdictTone(execution.verdict)}>{execution.verdict}</Badge>
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Latency</p>
                <p className="mt-1 text-sm font-medium text-ink">
                  {execution.latency_ms !== null ? formatMs(execution.latency_ms) : "—"}
                </p>
              </div>
              <div>
                <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">External ID</p>
                <p className="mt-1 truncate font-mono text-xs text-ink">{execution.external_execution_id}</p>
              </div>
              <div>
                <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Ingested</p>
                <p className="mt-1 text-xs text-ink-2">{new Date(execution.created_at).toLocaleString()}</p>
              </div>
            </div>

            {execution.error && (
              <Section label="Error">
                <p className="flex items-center gap-1.5 rounded-md bg-danger-soft px-2.5 py-2 text-xs text-danger">
                  <WarningIcon />
                  {execution.error}
                </p>
              </Section>
            )}

            <Section label="Input">
              <CodeBlock value={formatOutput(execution.input)} />
            </Section>

            <Section label="Actual output">
              <CodeBlock value={formatOutput(execution.actual_output)} />
            </Section>

            {execution.tool_calls.length > 0 && (
              <Section label="Tool calls">
                {/* A connected trace, not a plain list — the sequence
                    itself is real information (call order), so the
                    vertical line + numbered markers make that order
                    visible instead of implied by list position alone.
                    Markers tint danger for a failed call, so a broken
                    step in the sequence is visible before expanding it. */}
                <ol className="relative flex flex-col gap-3 border-l border-line pl-5">
                  {execution.tool_calls.map((tc, i) => (
                    <li
                      key={i}
                      className="animate-fade-in-up relative"
                      style={{ animationDelay: `${Math.min(i, 8) * 60}ms` }}
                    >
                      <span
                        className={`absolute top-1 -left-7 flex h-4 w-4 items-center justify-center rounded-full border-2 border-background text-[9px] font-semibold ${
                          tc.ok ? "bg-line-strong text-ink-2" : "bg-danger text-accent-ink"
                        }`}
                        aria-hidden="true"
                      >
                        {i + 1}
                      </span>
                      <ToolCallRow tc={tc} />
                    </li>
                  ))}
                </ol>
              </Section>
            )}

            <Section label="Evaluation checks">
              {execution.checks.length === 0 ? (
                <p className="text-xs text-ink-3">No checks were applicable to this execution.</p>
              ) : (
                <ul className="flex flex-col gap-1.5">
                  {execution.checks.map((check, i) => (
                    <CheckRow key={i} check={check} />
                  ))}
                </ul>
              )}
            </Section>

            <Section label="Root cause (deterministic)">
              {execution.rca_categories.length === 0 ? (
                <p className="text-xs text-ink-3">
                  No deterministic root-cause pattern matched — insufficient evidence for a
                  category, or nothing failed.
                </p>
              ) : (
                <ul className="flex flex-col gap-1.5">
                  {execution.rca_categories.map((finding, i) => (
                    <li key={i} className="rounded-md bg-surface px-2.5 py-2 text-xs">
                      <div className="flex items-center gap-2">
                        <Badge tone="danger">{finding.category}</Badge>
                        <span className="font-mono text-ink-3">{finding.check_type}</span>
                      </div>
                      <p className="mt-1 text-ink-2">{finding.detail}</p>
                    </li>
                  ))}
                </ul>
              )}
            </Section>

            {execution.verdict === "FAIL" && (
              <Section label="Regression candidate">
                <RegressionCandidatePanel executionId={execution.id} />
              </Section>
            )}
          </div>
        )}
      </div>
    </AppShell>
  );
}
