"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../../../components/AppShell";
import { Button } from "../../../components/ui/Button";
import { Card } from "../../../components/ui/Card";
import { Field } from "../../../components/ui/Input";
import { Skeleton } from "../../../components/ui/Skeleton";
import { ChevronLeftIcon } from "../../../components/ui/icons";
import {
  ApiError,
  clearToken,
  getAgent,
  updateAgent,
  type AgentRead,
  type AgentUpdate,
} from "../../../lib/api";
import { useRequireAuth } from "../../../lib/useRequireAuth";

const textareaClasses =
  "w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3 transition-colors duration-150 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/10";

function linesToArray(text: string): string[] | null {
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  return lines.length > 0 ? lines : null;
}

function arrayToLines(values: string[] | null): string {
  return values && values.length > 0 ? values.join("\n") : "";
}

interface FormState {
  name: string;
  description: string;
  isEnabled: boolean;
  expectedBehavior: string;
  forbiddenBehavior: string;
  allowedTools: string;
  requiredTools: string;
  outputSchema: string;
  latencyThreshold: string;
  defaultTimeout: string;
  minCallInterval: string;
}

function toFormState(agent: AgentRead): FormState {
  return {
    name: agent.name,
    description: agent.description ?? "",
    isEnabled: agent.is_enabled,
    expectedBehavior: arrayToLines(agent.default_expected_behavior),
    forbiddenBehavior: arrayToLines(agent.default_forbidden_behavior),
    allowedTools: arrayToLines(agent.default_allowed_tools),
    requiredTools: arrayToLines(agent.default_required_tools),
    outputSchema: agent.default_output_schema ? JSON.stringify(agent.default_output_schema, null, 2) : "",
    latencyThreshold:
      agent.default_latency_threshold_ms !== null ? String(agent.default_latency_threshold_ms) : "",
    defaultTimeout: String(agent.default_timeout_ms),
    minCallInterval: String(agent.min_call_interval_ms),
  };
}

// Reusable text-area field — same label/textarea structure repeated for
// every array-shaped default_* contract field below.
function LinesField({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
      {label}
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={3}
        className={`${textareaClasses} font-mono text-xs`}
      />
    </label>
  );
}

/** Takes the already-loaded Agent as a required prop and seeds its form
 * state via a lazy useState initializer — mounted only once `agent` is
 * available, so there is no effect needed to sync async data into local
 * state (avoids the setState-in-effect anti-pattern entirely). */
function AgentEditForm({
  agentId,
  agent,
  onSaved,
}: {
  agentId: string;
  agent: AgentRead;
  onSaved: () => void;
}) {
  const [initial] = useState<FormState>(() => toFormState(agent));
  const [form, setForm] = useState<FormState>(() => toFormState(agent));
  const [jsonError, setJsonError] = useState<string | null>(null);

  const updateMutation = useMutation({
    mutationFn: (payload: AgentUpdate) => updateAgent(agentId, payload),
    onSuccess: onSaved,
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setJsonError(null);

    let outputSchema: Record<string, unknown> | null = null;
    if (form.outputSchema.trim()) {
      try {
        outputSchema = JSON.parse(form.outputSchema);
      } catch {
        setJsonError("Output schema must be valid JSON.");
        return;
      }
    }

    // Only fields the user actually changed are sent — PATCH
    // /agents/{id} applies exactly the fields present in the request
    // body (backend/app/services/agent_service.py), so omitting
    // untouched fields here is what keeps them unmodified server-side.
    const payload: AgentUpdate = {};
    if (form.name !== initial.name) payload.name = form.name;
    if (form.description !== initial.description) payload.description = form.description || null;
    if (form.isEnabled !== initial.isEnabled) payload.is_enabled = form.isEnabled;
    if (form.expectedBehavior !== initial.expectedBehavior) {
      payload.default_expected_behavior = linesToArray(form.expectedBehavior);
    }
    if (form.forbiddenBehavior !== initial.forbiddenBehavior) {
      payload.default_forbidden_behavior = linesToArray(form.forbiddenBehavior);
    }
    if (form.allowedTools !== initial.allowedTools) {
      payload.default_allowed_tools = linesToArray(form.allowedTools);
    }
    if (form.requiredTools !== initial.requiredTools) {
      payload.default_required_tools = linesToArray(form.requiredTools);
    }
    if (form.outputSchema !== initial.outputSchema) {
      payload.default_output_schema = outputSchema;
    }
    if (form.latencyThreshold !== initial.latencyThreshold) {
      payload.default_latency_threshold_ms = form.latencyThreshold.trim()
        ? Number(form.latencyThreshold)
        : null;
    }
    if (form.defaultTimeout !== initial.defaultTimeout) {
      payload.default_timeout_ms = Number(form.defaultTimeout);
    }
    if (form.minCallInterval !== initial.minCallInterval) {
      payload.min_call_interval_ms = Number(form.minCallInterval);
    }

    if (Object.keys(payload).length === 0) {
      onSaved();
      return;
    }

    updateMutation.mutate(payload);
  }

  return (
    <Card className="mt-6" elevation="raised">
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <Field label="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />

        <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
          Description
          <textarea
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            rows={2}
            className={textareaClasses}
          />
        </label>

        <label className="flex items-center gap-2 text-sm font-medium text-ink-2">
          <input
            type="checkbox"
            checked={form.isEnabled}
            onChange={(e) => setForm({ ...form, isEnabled: e.target.checked })}
            className="h-4 w-4 accent-accent rounded border-line-strong text-accent focus-visible:ring-4 focus-visible:ring-accent/10"
          />
          Enabled
        </label>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <LinesField
            label="Expected behavior (one per line)"
            value={form.expectedBehavior}
            onChange={(v) => setForm({ ...form, expectedBehavior: v })}
          />
          <LinesField
            label="Forbidden behavior (one per line)"
            value={form.forbiddenBehavior}
            onChange={(v) => setForm({ ...form, forbiddenBehavior: v })}
          />
          <LinesField
            label="Allowed tools (one per line)"
            value={form.allowedTools}
            onChange={(v) => setForm({ ...form, allowedTools: v })}
          />
          <LinesField
            label="Required tools (one per line)"
            value={form.requiredTools}
            onChange={(v) => setForm({ ...form, requiredTools: v })}
          />
        </div>

        <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
          Output schema (JSON, optional)
          <textarea
            value={form.outputSchema}
            onChange={(e) => setForm({ ...form, outputSchema: e.target.value })}
            rows={4}
            placeholder="{}"
            className={`${textareaClasses} font-mono text-xs`}
          />
        </label>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field
            label="Latency threshold (ms)"
            type="number"
            min={0}
            value={form.latencyThreshold}
            onChange={(e) => setForm({ ...form, latencyThreshold: e.target.value })}
            placeholder="—"
          />
          <Field
            label="Default timeout (ms)"
            type="number"
            min={0}
            value={form.defaultTimeout}
            onChange={(e) => setForm({ ...form, defaultTimeout: e.target.value })}
            required
          />
          <Field
            label="Min call interval (ms)"
            type="number"
            min={0}
            value={form.minCallInterval}
            onChange={(e) => setForm({ ...form, minCallInterval: e.target.value })}
            required
          />
        </div>

        <div className="flex items-center gap-2">
          <Button type="submit" variant="primary" disabled={updateMutation.isPending}>
            {updateMutation.isPending ? "Saving…" : "Save changes"}
          </Button>
          <Link href={`/agents/${agentId}`} className="no-underline">
            <Button type="button" variant="tertiary">
              Cancel
            </Button>
          </Link>
        </div>

        {jsonError && <p className="text-xs text-danger">{jsonError}</p>}
        {updateMutation.isError && (
          <p className="text-xs text-danger">
            {updateMutation.error instanceof ApiError ? updateMutation.error.message : "Could not save changes."}
          </p>
        )}
      </form>
    </Card>
  );
}

export default function EditAgentPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const checkedAuth = useRequireAuth();

  const agentQuery = useQuery({
    queryKey: ["agent", agentId],
    queryFn: () => getAgent(agentId),
    enabled: checkedAuth,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  function handleSaved() {
    queryClient.invalidateQueries({ queryKey: ["agent", agentId] });
    router.push(`/agents/${agentId}`);
  }

  if (!checkedAuth) return null;

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href={`/agents/${agentId}`}
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        Agent
      </Link>
      <p className="text-sm font-semibold text-ink">Edit</p>
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-2xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Edit agent</h1>

        {agentQuery.isLoading && (
          <div className="mt-6 flex flex-col gap-3">
            <Skeleton className="h-10" />
            <Skeleton className="h-24" />
          </div>
        )}

        {agentQuery.isError && (
          <p className="mt-6 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {agentQuery.error instanceof ApiError ? agentQuery.error.message : "Could not load this agent."}
          </p>
        )}

        {agentQuery.data && <AgentEditForm agentId={agentId} agent={agentQuery.data} onSaved={handleSaved} />}
      </div>
    </AppShell>
  );
}
