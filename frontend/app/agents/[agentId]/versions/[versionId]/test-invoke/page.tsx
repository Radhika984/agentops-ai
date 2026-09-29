"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { AppShell } from "../../../../../components/AppShell";
import { Badge, type Tone } from "../../../../../components/ui/Badge";
import { Button } from "../../../../../components/ui/Button";
import { CodeBlock, Disclosure, LabeledCodeBlock } from "../../../../../components/ui/CodeDisclosure";
import { Section } from "../../../../../components/ui/Section";
import { ChevronLeftIcon, WarningIcon } from "../../../../../components/ui/icons";
import {
  ApiError,
  clearToken,
  testInvokeAgentVersion,
  type AgentExecution,
  type ProductionToolCallRecord,
} from "../../../../../lib/api";
import { useRequireAuth } from "../../../../../lib/useRequireAuth";

const textareaClasses =
  "w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3 transition-colors duration-150 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/10 font-mono text-xs";

function statusTone(status: AgentExecution["status"]): Tone {
  if (status === "ok") return "success";
  if (status === "timeout") return "warning";
  return "danger";
}

function formatMs(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function formatOutput(value: AgentExecution["output"]): string {
  if (value === null || value === undefined) return "(no output)";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

/** Same expandable INPUT/OUTPUT disclosure pattern used by RunAgentPanel
 * and the Phase 20 execution detail page — reused a third time here
 * rather than re-invented, for a real AgentExecution's own tool calls. */
function ToolCallRow({ tc }: { tc: ProductionToolCallRecord }) {
  return (
    <Disclosure
      variant="row"
      summary={<span className="font-mono font-medium text-ink">{tc.tool_name}</span>}
      meta={
        <>
          <Badge tone={tc.ok ? "success" : "danger"}>{tc.ok ? "completed" : "failed"}</Badge>
          <span className="text-ink-3">{tc.duration_ms !== null ? `${tc.duration_ms}ms` : "—"}</span>
        </>
      }
    >
      <LabeledCodeBlock label="Input" value={tc.input} />
      <LabeledCodeBlock label="Output" value={tc.output} />
    </Disclosure>
  );
}

export default function TestInvokePage() {
  const { agentId, versionId } = useParams<{ agentId: string; versionId: string }>();
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  const [input, setInput] = useState("{}");
  const [inputError, setInputError] = useState<string | null>(null);

  const invokeMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      testInvokeAgentVersion(agentId, versionId, payload),
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setInputError(null);
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(input || "{}");
    } catch {
      setInputError("Input must be valid JSON.");
      return;
    }
    invokeMutation.mutate(parsed);
  }

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const execution = invokeMutation.data;

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href={`/agents/${agentId}`}
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        Agent
      </Link>
      <p className="truncate font-mono text-sm font-semibold text-ink">{versionId}</p>
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-3xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Test invoke</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          A single real invocation of this Agent Version — this is a test invocation only, not a
          Suite Run; no TestCaseResult or evaluation verdict is created or persisted from this call.
        </p>

        <div className="mt-6 overflow-hidden rounded-lg border border-line bg-surface-elevated shadow-md">
          <form onSubmit={handleSubmit} className="flex flex-col gap-3 px-4 py-3.5">
            <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
              Input (JSON)
              <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={5} className={textareaClasses} />
            </label>
            <div>
              <Button type="submit" variant="primary" disabled={invokeMutation.isPending}>
                {invokeMutation.isPending ? "Invoking…" : "Invoke"}
              </Button>
            </div>
            {inputError && <p className="text-xs text-danger">{inputError}</p>}
            {invokeMutation.isError && (
              <p className="flex items-center gap-1.5 text-xs text-danger">
                <WarningIcon />
                {invokeMutation.error instanceof ApiError
                  ? invokeMutation.error.message
                  : "Could not invoke this agent version."}
              </p>
            )}
          </form>

          {execution && (
            <>
              <div className="grid grid-cols-3 gap-3 border-t border-line px-4 py-3.5">
                <div>
                  <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Status</p>
                  <p className="mt-1">
                    <Badge tone={statusTone(execution.status)}>{execution.status}</Badge>
                  </p>
                </div>
                <div>
                  <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Latency</p>
                  <p className="mt-1 text-sm font-medium text-ink">{formatMs(execution.latency_ms)}</p>
                </div>
                <div>
                  <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Request ID</p>
                  <p className="mt-1 truncate font-mono text-xs text-ink-3">{execution.request_id}</p>
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

              <Section label="Output">
                <CodeBlock value={formatOutput(execution.output)} />
              </Section>

              {execution.tool_calls.length > 0 && (
                <Section label={`Tool calls (${execution.tool_calls.length})`}>
                  <div className="flex flex-col gap-2">
                    {execution.tool_calls.map((tc, i) => (
                      <ToolCallRow key={i} tc={tc} />
                    ))}
                  </div>
                </Section>
              )}

              {execution.trace && execution.trace.length > 0 && (
                <Section label="Trace">
                  <ol className="flex flex-col">
                    {execution.trace.map((span, i) => (
                      <li key={i} className="relative flex gap-3 pb-3 last:pb-0">
                        <div className="flex flex-col items-center">
                          <span className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                          {execution.trace && i < execution.trace.length - 1 && (
                            <span className="w-px flex-1 bg-line-strong" />
                          )}
                        </div>
                        <div className="flex flex-1 items-center justify-between pb-0.5 text-xs">
                          <span className="font-mono text-ink-2">{span.name}</span>
                          <span className="text-ink-3">
                            {span.duration_ms !== null ? `${span.duration_ms}ms` : "—"}
                          </span>
                        </div>
                      </li>
                    ))}
                  </ol>
                </Section>
              )}

              {(execution.token_usage || execution.model_info) && (
                <Section label="Model info">
                  <CodeBlock
                    value={{ token_usage: execution.token_usage, model_info: execution.model_info }}
                  />
                </Section>
              )}
            </>
          )}
        </div>
      </div>
    </AppShell>
  );
}
