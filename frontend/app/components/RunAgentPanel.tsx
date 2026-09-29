"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ApiError,
  createRun,
  getRun,
  requestRelease,
  type RunRead,
  type RunState,
  type RunStatus,
  type TraceSpanRecord,
} from "../lib/api";
import { Badge, type Tone } from "./ui/Badge";
import { Button } from "./ui/Button";
import { TextInput } from "./ui/Input";
import { Disclosure, LabeledCodeBlock } from "./ui/CodeDisclosure";
import { Section } from "./ui/Section";
import { StatusDot, StatusLabel } from "./ui/Status";
import { CheckIcon, ChevronDownIcon, CloseIcon, WarningIcon } from "./ui/icons";

const TERMINAL_STATUSES: RunStatus[] = ["succeeded", "failed"];
const POLL_INTERVAL_MS = 1500;

function statusTone(status: RunStatus): Tone {
  if (status === "succeeded") return "success";
  if (status === "failed") return "danger";
  return "accent";
}

function statusLabel(status: string): string {
  // AgentState's / ReleaseSnapshot's own status vocabulary (backend/app/
  // agents/state.py, backend/app/approvals/service.py) — shown verbatim,
  // just formatted for reading.
  return status.replace(/_/g, " ");
}

function flagTone(severity: string): Tone {
  if (severity === "high") return "danger";
  if (severity === "medium") return "warning";
  return "neutral";
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

/** Wall-clock duration from the run's own timestamps — real, not a
 * fabricated per-run metric. Only shown once the run has actually
 * finished (created_at/updated_at stop moving at that point). */
function runDuration(run: RunRead): string | null {
  if (!TERMINAL_STATUSES.includes(run.status)) return null;
  const ms = new Date(run.updated_at).getTime() - new Date(run.created_at).getTime();
  if (!Number.isFinite(ms) || ms < 0) return null;
  return formatMs(ms);
}

function ScoreBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const tone = score >= 0.8 ? "bg-success" : score >= 0.5 ? "bg-warning" : "bg-danger";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
      <div className={`h-full rounded-full ${tone} transition-all duration-300`} style={{ width: `${pct}%` }} />
    </div>
  );
}

/** The one genuinely prominent, "impossible to miss" moment in this
 * panel — a completed release decision. Everything else in the panel is
 * quiet technical detail; this is deliberately not. */
function ReleaseVerdict({ decision }: { decision: "ship" | "hold" | "rollback" }) {
  const copy = {
    ship: { label: "Ready to release", tone: "success" as Tone },
    hold: { label: "Hold release", tone: "warning" as Tone },
    rollback: { label: "Release blocked", tone: "danger" as Tone },
  }[decision];

  return (
    <div
      className={`flex items-center gap-2.5 rounded-md px-3.5 py-3 text-base font-semibold ${
        copy.tone === "success"
          ? "bg-success-soft text-success"
          : copy.tone === "warning"
            ? "bg-warning-soft text-warning"
            : "bg-danger-soft text-danger"
      }`}
    >
      {copy.tone === "success" ? <CheckIcon /> : <CloseIcon />}
      {copy.label.toUpperCase()}
    </div>
  );
}

// ---- Evaluation pipeline — a compact, at-a-glance summary of the real
// graph stages a run goes through (backend/app/agents/graph.py: Planner
// -> Evaluation -> Hallucination -> Verification, plus the Phase 9
// release-review workflow). Every field below is derived from data the
// API already returns (plan, retrieved_memory, tool_calls, flags,
// evaluations, trace, verification_passed, release) — nothing here is a
// fabricated status; a stage neither invents a state it can't back with
// real data nor claims to be "done" before its real output exists. ----

type StageState = "waiting" | "running" | "pass" | "warning" | "fail";

interface Stage {
  key: string;
  label: string;
  state: StageState;
  detail: string;
}

function traceDuration(trace: TraceSpanRecord[] | undefined, name: string): number | null {
  if (!trace) return null;
  const matches = trace.filter((span) => span.name === name);
  return matches.length > 0 ? matches[matches.length - 1].duration_ms : null;
}

function buildStages(run: RunRead): Stage[] {
  const s = run.state;
  const status = run.status;

  const safetyFlags = s.flags.filter((f) => f.agent === "safety");
  const hallucinationFlags = s.flags.filter((f) => f.agent === "hallucination");
  const latestEval = s.evaluations.length > 0 ? s.evaluations[s.evaluations.length - 1] : null;
  const toolsReached = s.tool_calls.length > 0;

  const plannerDuration = traceDuration(s.trace, "planner");
  const evaluationDuration = traceDuration(s.trace, "evaluation");
  const hallucinationDuration = traceDuration(s.trace, "hallucination");
  const verificationDuration = traceDuration(s.trace, "verification");

  const stages: Stage[] = [];

  stages.push({
    key: "planner",
    label: "Planner",
    state: s.plan.length > 0 ? "pass" : status === "planning" ? "running" : "waiting",
    detail:
      s.plan.length > 0
        ? `${s.plan.length} task${s.plan.length === 1 ? "" : "s"} planned` +
          (plannerDuration !== null ? ` · ${formatMs(plannerDuration)}` : "")
        : status === "planning"
          ? "Decomposing goal…"
          : "Not started",
  });

  stages.push({
    key: "memory",
    label: "Memory",
    state: s.plan.length > 0 ? "pass" : status === "planning" ? "running" : "waiting",
    detail:
      s.plan.length > 0
        ? s.retrieved_memory.length > 0
          ? `${s.retrieved_memory.length} similar past run${s.retrieved_memory.length === 1 ? "" : "s"} retrieved`
          : "No similar past runs found"
        : "Not started",
  });

  stages.push({
    key: "tools",
    label: "Tools",
    state: toolsReached
      ? s.tool_calls.some((t) => !t.ok)
        ? "warning"
        : "pass"
      : status === "planning" || status === "verifying"
        ? "running"
        : "waiting",
    detail: toolsReached
      ? `${s.tool_calls.length} call${s.tool_calls.length === 1 ? "" : "s"} · ${s.tool_calls.filter((t) => t.ok).length} ok`
      : "No tool calls yet",
  });

  stages.push({
    key: "safety",
    label: "Safety",
    state: !toolsReached ? "waiting" : safetyFlags.length > 0 ? "fail" : "pass",
    detail: !toolsReached
      ? "Not evaluated yet"
      : safetyFlags.length > 0
        ? `${safetyFlags.length} call${safetyFlags.length === 1 ? "" : "s"} blocked`
        : `${s.tool_calls.length} tool call${s.tool_calls.length === 1 ? "" : "s"} checked`,
  });

  stages.push({
    key: "evaluation",
    label: "Evaluation",
    state: latestEval ? (latestEval.passed ? "pass" : "fail") : status === "evaluating" ? "running" : "waiting",
    detail: latestEval
      ? `Score ${Math.round(latestEval.score * 100)}/100` +
        (evaluationDuration !== null ? ` · ${formatMs(evaluationDuration)}` : "")
      : status === "evaluating"
        ? "Scoring plan…"
        : "Not started",
  });

  const hallucinationReached = hallucinationDuration !== null;
  stages.push({
    key: "hallucination",
    label: "Hallucination",
    state: !hallucinationReached
      ? status === "checking_hallucination"
        ? "running"
        : "waiting"
      : hallucinationFlags.length > 0
        ? "warning"
        : "pass",
    detail: !hallucinationReached
      ? status === "checking_hallucination"
        ? "Checking claims against context…"
        : "Not started"
      : hallucinationFlags.length > 0
        ? `${hallucinationFlags.length} unsupported claim${hallucinationFlags.length === 1 ? "" : "s"} flagged` +
          (hallucinationDuration !== null ? ` · ${formatMs(hallucinationDuration)}` : "")
        : `No unsupported claims found · ${formatMs(hallucinationDuration)}`,
  });

  const verificationReached = verificationDuration !== null;
  stages.push({
    key: "verification",
    label: "Verification",
    state: !verificationReached ? (status === "verifying" ? "running" : "waiting") : s.verification_passed ? "pass" : "fail",
    detail: !verificationReached
      ? status === "verifying"
        ? "Running verification checks…"
        : "Not started"
      : (s.verification_passed ? "Passed" : "Failed") +
        (verificationDuration !== null ? ` · ${formatMs(verificationDuration)}` : "") +
        (s.retry_count > 0 ? ` · retried ${s.retry_count}×` : ""),
  });

  const release = s.release;
  if (release) {
    stages.push({
      key: "release",
      label: "Release",
      state:
        release.decision === "ship"
          ? "pass"
          : release.decision === "rollback"
            ? "fail"
            : release.decision === "hold"
              ? "warning"
              : "running",
      detail: release.decision
        ? release.decision === "ship"
          ? "Ready to release"
          : release.decision === "hold"
            ? "Held — hard gate failed"
            : "Blocked — release rejected"
        : "Awaiting review decision",
    });
  } else if (TERMINAL_STATUSES.includes(status)) {
    stages.push({ key: "release", label: "Release", state: "waiting", detail: "Not yet requested" });
  }

  return stages;
}

/** The concise "here's exactly why" checklist behind a release verdict —
 * every row is a real signal already present on the run (flags by
 * agent, verification_passed, the hard gate itself), not an invented
 * criterion. */
function ReleaseChecklist({ run }: { run: RunRead }) {
  const safetyOk = !run.state.flags.some((f) => f.agent === "safety");
  const hallucinationOk = !run.state.flags.some((f) => f.agent === "hallucination");
  const rows: Array<{ label: string; ok: boolean }> = [
    { label: "Safety checks", ok: safetyOk },
    { label: "Hallucination checks", ok: hallucinationOk },
    { label: "Verification", ok: run.state.verification_passed },
  ];

  return (
    <ul className="flex flex-col gap-1.5">
      {rows.map((row) => (
        <li key={row.label} className="flex items-center justify-between text-xs">
          <span className="text-ink-2">{row.label}</span>
          <span
            className={`flex items-center gap-1 font-medium ${row.ok ? "text-success" : "text-danger"}`}
          >
            {row.ok ? <CheckIcon /> : <CloseIcon />}
            {row.ok ? "Passed" : "Failed"}
          </span>
        </li>
      ))}
    </ul>
  );
}

function StageIcon({ state }: { state: StageState }) {
  if (state === "pass") return <CheckIcon className="text-success" />;
  if (state === "fail") return <CloseIcon className="text-danger" />;
  if (state === "warning") return <WarningIcon className="text-warning" />;
  if (state === "running") return <StatusDot tone="accent" pulse />;
  return <StatusDot tone="neutral" />;
}

/** One expandable tool-call inspection row — reused both inside the
 * "Tools" trace step below and nowhere else, so the same technical
 * INPUT/OUTPUT presentation never has two different implementations. */
function ToolCallRow({ tc }: { tc: RunState["tool_calls"][number] }) {
  return (
    <Disclosure
      variant="row"
      summary={<span className="font-mono font-medium text-ink">{tc.tool_name}</span>}
      meta={
        <>
          <Badge tone={tc.ok ? "success" : "danger"}>{tc.ok ? "completed" : "failed"}</Badge>
          <span className="text-ink-3">{tc.duration_ms}ms</span>
        </>
      }
    >
      <LabeledCodeBlock label="Input" value={tc.input} />
      <LabeledCodeBlock label="Output" value={tc.output} />
    </Disclosure>
  );
}

/** Stage-specific expanded detail — the real underlying data behind each
 * trace step (a plan, retrieved memories, tool calls, flags, an
 * evaluation score, a trace span). Returns null when a stage has nothing
 * more to show than its one-line summary already does (never renders an
 * empty/placeholder expansion). */
function stageDetail(key: string, run: RunRead): ReactNode {
  const s = run.state;
  if (key === "planner" && s.plan.length > 0) {
    return (
      <ol className="flex flex-col gap-1.5">
        {s.plan.map((task, i) => (
          <li key={i} className="flex gap-2 text-ink-2">
            <span className="text-ink-3">{i + 1}.</span>
            {task}
          </li>
        ))}
      </ol>
    );
  }
  if (key === "memory" && s.retrieved_memory.length > 0) {
    return (
      <ul className="flex flex-col gap-1.5">
        {s.retrieved_memory.map((memory, i) => (
          <li key={i} className="whitespace-pre-wrap rounded-md bg-surface px-2.5 py-1.5 text-ink-2">
            {memory}
          </li>
        ))}
      </ul>
    );
  }
  if (key === "tools" && s.tool_calls.length > 0) {
    return (
      <ul className="flex flex-col gap-2">
        {s.tool_calls.map((tc, i) => (
          <li key={i}>
            <ToolCallRow tc={tc} />
          </li>
        ))}
      </ul>
    );
  }
  if (key === "safety" || key === "hallucination") {
    const flags = s.flags.filter((f) => f.agent === key);
    if (flags.length === 0) return null;
    return (
      <ul className="flex flex-col gap-1.5">
        {flags.map((flag, i) => (
          <li key={i} className="rounded-md bg-surface px-2.5 py-1.5">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-ink">{flag.type}</span>
              <Badge tone={flagTone(flag.severity)}>{flag.severity}</Badge>
            </div>
            <p className="mt-0.5 whitespace-pre-wrap text-ink-3">{flag.details}</p>
          </li>
        ))}
      </ul>
    );
  }
  if (key === "evaluation" && s.evaluations.length > 0) {
    const latest = s.evaluations[s.evaluations.length - 1];
    return (
      <div>
        <div className="flex items-center justify-between">
          <span className="text-ink-2">{latest.passed ? "Passed" : "Failed"}</span>
          <span className="font-semibold text-ink">
            {Math.round(latest.score * 100)}
            <span className="font-normal text-ink-3"> / 100</span>
          </span>
        </div>
        <div className="mt-1.5">
          <ScoreBar score={latest.score} />
        </div>
      </div>
    );
  }
  return null;
}

/**
 * The evaluation run rendered as a numbered, expandable trace — the same
 * shape a distributed-tracing viewer uses for a request, applied to an
 * agent run: Planner -> Memory -> Tools -> Safety -> Evaluation ->
 * Hallucination -> Verification -> Release. Every stage's state, detail
 * line and expanded content are derived strictly from fields the API
 * already returns; a stage with no real sub-data to show (e.g. Safety
 * before any tool call has happened) never expands to an empty box —
 * `stageDetail` returns null and no <details> wrapper appears.
 *
 * This replaces what used to be five separate sections (Plan, Evaluation
 * score, Retrieved memory, Tool calls, Flags) stacked below a compact
 * status list — consolidating the *same* underlying data into the trace
 * itself, once, instead of showing it twice in two different layouts.
 */
function RunTrace({ run }: { run: RunRead }) {
  const stages = buildStages(run);
  return (
    <ol className="flex flex-col gap-1.5">
      {stages.map((stage, i) => {
        const detail = stageDetail(stage.key, run);
        const row = (
          <div className="flex items-center gap-2.5 py-1.5">
            <span className="w-5 shrink-0 font-mono text-[11px] text-ink-3">
              {String(i + 1).padStart(2, "0")}
            </span>
            <span className="flex h-4 w-4 shrink-0 items-center justify-center">
              <StageIcon state={stage.state} />
            </span>
            <div className="min-w-0 flex-1">
              <span
                className={`text-sm font-medium ${stage.state === "waiting" ? "text-ink-3" : "text-ink"}`}
              >
                {stage.label}
              </span>
              <p className="text-xs text-ink-3">{stage.detail}</p>
            </div>
            {detail && (
              <ChevronDownIcon className="shrink-0 text-ink-3 transition-transform duration-150 group-open:rotate-180" />
            )}
          </div>
        );

        return (
          <li key={stage.key} className="rounded-md">
            {detail ? (
              <details className="group">
                <summary className="cursor-pointer list-none [&::-webkit-details-marker]:hidden">
                  {row}
                </summary>
                <div className="ml-7 mb-2 rounded-md bg-surface-2/70 px-2.5 py-2 text-xs">
                  {detail}
                </div>
              </details>
            ) : (
              row
            )}
          </li>
        );
      })}
    </ol>
  );
}

export function RunAgentPanel({ projectId }: { projectId: string }) {
  const [goal, setGoal] = useState("");
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const createMutation = useMutation({
    mutationFn: () => createRun(projectId, goal),
    onSuccess: (run) => {
      setActiveRunId(run.id);
    },
  });

  const runQuery = useQuery({
    queryKey: ["run", projectId, activeRunId],
    queryFn: () => getRun(projectId, activeRunId as string),
    enabled: activeRunId !== null,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && TERMINAL_STATUSES.includes(status) ? false : POLL_INTERVAL_MS;
    },
  });

  const releaseMutation = useMutation({
    mutationFn: () => requestRelease(projectId, activeRunId as string),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", projectId, activeRunId] });
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!goal.trim() || createMutation.isPending) return;
    createMutation.mutate();
  }

  const run = runQuery.data;
  const isPolling = run !== undefined && !TERMINAL_STATUSES.includes(run.status);
  const release = run?.state.release;

  return (
    <aside className="flex max-h-[70vh] flex-col overflow-y-auto rounded-lg border border-line bg-surface-elevated shadow-md md:h-full md:max-h-none">
      <div className="px-4 py-3.5">
        <h2 className="text-sm font-semibold text-ink">Evaluation console</h2>
        <p className="mt-0.5 text-xs text-ink-3">
          Planner → Evaluation → Hallucination → Verification, with a bounded retry on failure.
        </p>

        <form onSubmit={handleSubmit} className="mt-3.5 flex flex-col gap-1.5">
          <label className="text-xs font-medium text-ink-2" htmlFor="evaluation-goal">
            Evaluation goal
          </label>
          <TextInput
            id="evaluation-goal"
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
            placeholder="Describe what the agent should accomplish…"
            disabled={createMutation.isPending}
          />
          <Button
            type="submit"
            variant="primary"
            disabled={createMutation.isPending || !goal.trim()}
          >
            {createMutation.isPending ? "Starting…" : "Start evaluation"}
          </Button>
        </form>

        {createMutation.isError && (
          <p className="mt-2 text-xs text-danger">
            {createMutation.error instanceof ApiError
              ? createMutation.error.message
              : "Could not start the run."}
          </p>
        )}
      </div>

      {run && (
        <div className="flex-1">
          {/* A compact "trace header" — the three facts a real
              observability tool leads with (status, release verdict,
              duration). Duration only appears once the run has actually
              finished; there is no per-run cost/model figure to show
              here (cost is tracked per model-call, not per run — see the
              Cost dashboard), so it's deliberately omitted rather than
              approximated. */}
          <div className="grid grid-cols-3 gap-3 border-t border-line px-4 py-3.5 first:border-t-0">
            <div>
              <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Status</p>
              <div className="mt-1">
                <StatusLabel tone={statusTone(run.status)} pulse={isPolling}>
                  {statusLabel(run.status)}
                </StatusLabel>
              </div>
              {run.state.retry_count > 0 && (
                <p className="mt-1 text-[11px] text-ink-3">
                  Retried {run.state.retry_count}×
                </p>
              )}
            </div>
            <div>
              <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Release</p>
              <p className="mt-1 text-sm font-medium text-ink">
                {release?.decision
                  ? release.decision === "ship"
                    ? "Ready"
                    : release.decision === "hold"
                      ? "Hold"
                      : "Blocked"
                  : release
                    ? "Reviewing…"
                    : "—"}
              </p>
            </div>
            <div>
              <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Duration</p>
              <p className="mt-1 text-sm font-medium text-ink">{runDuration(run) ?? "—"}</p>
            </div>
          </div>

          <Section label="Evaluation trace">
            <RunTrace run={run} />
          </Section>

          {run.state.trace && run.state.trace.length > 0 && (
            <Section label="Span timing">
              <ol className="flex flex-col">
                {run.state.trace.map((span, i) => (
                  <li key={i} className="relative flex gap-3 pb-3 last:pb-0">
                    <div className="flex flex-col items-center">
                      <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                      {i < run.state.trace!.length - 1 && (
                        <span className="w-px flex-1 bg-line-strong" />
                      )}
                    </div>
                    <div className="flex flex-1 items-center justify-between pb-0.5 text-xs">
                      <span className="font-mono text-ink-2">{span.name}</span>
                      <span className="text-ink-3">{span.duration_ms}ms</span>
                    </div>
                  </li>
                ))}
              </ol>
            </Section>
          )}

          {!isPolling && !release && (
            <Section label="Release">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => releaseMutation.mutate()}
                disabled={releaseMutation.isPending}
              >
                {releaseMutation.isPending ? "Reviewing…" : "Request release review"}
              </Button>
              {releaseMutation.isError && (
                <p className="mt-1.5 text-xs text-danger">
                  {releaseMutation.error instanceof ApiError
                    ? releaseMutation.error.message
                    : "Could not start the release review."}
                </p>
              )}
            </Section>
          )}

          {release && (
            <div className="border-t border-line px-4 py-3.5">
              <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">
                Release review
              </p>

              <div className="glass mt-2 flex flex-col gap-3 rounded-lg border p-3">
                {release.decision ? (
                  <ReleaseVerdict decision={release.decision} />
                ) : (
                  <span className="text-xs text-ink-3">{statusLabel(release.status)}</span>
                )}

                <ReleaseChecklist run={run} />
                <p className="text-[11px] text-ink-3">
                  Performance and cost aren&apos;t part of this per-run gate — see the Cost
                  dashboard for spend and volume across all runs.
                </p>

                {release.root_cause && (
                  <div className="rounded-md bg-surface-2/70 px-2.5 py-2 text-xs">
                    <p className="font-medium text-ink">Root cause</p>
                    <p className="mt-0.5 text-ink-2">{release.root_cause}</p>
                    {release.root_cause_pattern && (
                      <p className="mt-1 text-ink-3">Pattern: {release.root_cause_pattern}</p>
                    )}
                  </div>
                )}

                {release.auto_fix_proposed_task && (
                  <div className="rounded-md bg-surface-2/70 px-2.5 py-2 text-xs">
                    <p className="font-medium text-ink">Auto fix</p>
                    <p className="mt-0.5 text-ink-2">{release.auto_fix_proposed_task}</p>
                    <p className="mt-1">
                      <Badge tone={release.auto_fix_applied ? "success" : "neutral"}>
                        {release.auto_fix_applied ? "Applied" : "Awaiting decision"}
                      </Badge>
                    </p>
                  </div>
                )}

                {release.soft_score !== null && (
                  <div className="flex items-center justify-between rounded-md bg-surface-2/70 px-2.5 py-2 text-xs">
                    <span className="font-medium text-ink">Confidence score</span>
                    <span className="font-semibold text-ink">
                      {(release.soft_score * 100).toFixed(0)}
                      <span className="font-normal text-ink-3"> / 100</span>
                    </span>
                  </div>
                )}

                {(release.status === "awaiting_auto_fix_approval" ||
                  release.status === "awaiting_release_approval") && (
                  <p className="text-xs font-medium text-warning">
                    Awaiting approval — see the Approvals queue.
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </aside>
  );
}
