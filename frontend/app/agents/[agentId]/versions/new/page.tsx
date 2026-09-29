"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../../../../components/AppShell";
import { Button } from "../../../../components/ui/Button";
import { Card } from "../../../../components/ui/Card";
import { Field } from "../../../../components/ui/Input";
import { SelectField } from "../../../../components/ui/Select";
import { ChevronLeftIcon } from "../../../../components/ui/icons";
import { ApiError, clearToken, createAgentVersion } from "../../../../lib/api";
import { useRequireAuth } from "../../../../lib/useRequireAuth";

const textareaClasses =
  "w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3 transition-colors duration-150 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/10 font-mono text-xs";

export default function CreateAgentVersionPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const checkedAuth = useRequireAuth();

  const [label, setLabel] = useState("");
  const [adapterType, setAdapterType] = useState<"http" | "local">("http");
  const [observabilityLevel, setObservabilityLevel] = useState("2");

  // HTTPAdapterConfig fields (backend/app/adapters/http_adapter.py)
  const [url, setUrl] = useState("");
  const [method, setMethod] = useState("POST");
  const [headers, setHeaders] = useState("{}");
  const [timeoutMs, setTimeoutMs] = useState("30000");

  // LocalAdapterConfig fields (backend/app/adapters/local_adapter.py)
  const [modulePath, setModulePath] = useState("");
  const [callableName, setCallableName] = useState("invoke");

  const [configError, setConfigError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () => {
      const adapter_config =
        adapterType === "http"
          ? { url, method, headers: JSON.parse(headers || "{}"), timeout_ms: Number(timeoutMs) }
          : { module_path: modulePath, callable_name: callableName };
      return createAgentVersion(agentId, {
        label,
        adapter_type: adapterType,
        adapter_config,
        observability_level: Number(observabilityLevel),
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent-versions", agentId] });
      router.push(`/agents/${agentId}`);
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setConfigError(null);
    if (adapterType === "http") {
      try {
        JSON.parse(headers || "{}");
      } catch {
        setConfigError("Headers must be valid JSON.");
        return;
      }
    }
    createMutation.mutate();
  }

  function handleLogout() {
    clearToken();
    router.replace("/login");
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
      <p className="text-sm font-semibold text-ink">New version</p>
    </div>
  );

  const isValid =
    label.trim().length > 0 &&
    (adapterType === "http" ? url.trim().length > 0 : modulePath.trim().length > 0);

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-2xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">New agent version</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          A version is an immutable connection snapshot — its adapter configuration can&apos;t be
          changed once created; connect a new version instead of editing this one.
        </p>

        <Card className="mt-6" elevation="raised">
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field
                label="Label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. v1, staging, 2026-09-17"
                required
              />
              <Field
                label="Observability level (1–4)"
                type="number"
                min={1}
                max={4}
                value={observabilityLevel}
                onChange={(e) => setObservabilityLevel(e.target.value)}
                required
              />
            </div>

            <SelectField
              label="Adapter type"
              value={adapterType}
              onChange={(e) => setAdapterType(e.target.value as "http" | "local")}
            >
              <option value="http">HTTP</option>
              <option value="local">Local</option>
            </SelectField>

            {adapterType === "http" ? (
              <div className="flex flex-col gap-4 rounded-md border border-line bg-surface p-3">
                <Field
                  label="URL"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://your-agent.example.com/invoke"
                  required
                />
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Field
                    label="Method"
                    value={method}
                    onChange={(e) => setMethod(e.target.value)}
                    placeholder="POST"
                  />
                  <Field
                    label="Timeout (ms)"
                    type="number"
                    min={0}
                    value={timeoutMs}
                    onChange={(e) => setTimeoutMs(e.target.value)}
                  />
                </div>
                <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
                  Headers (JSON)
                  <textarea
                    value={headers}
                    onChange={(e) => setHeaders(e.target.value)}
                    rows={3}
                    className={textareaClasses}
                  />
                </label>
              </div>
            ) : (
              <div className="flex flex-col gap-4 rounded-md border border-line bg-surface p-3">
                <Field
                  label="Module path"
                  value={modulePath}
                  onChange={(e) => setModulePath(e.target.value)}
                  placeholder="myapp.agents.support"
                  required
                />
                <Field
                  label="Callable name"
                  value={callableName}
                  onChange={(e) => setCallableName(e.target.value)}
                  placeholder="invoke"
                />
              </div>
            )}

            <div className="flex items-center gap-2">
              <Button type="submit" variant="primary" disabled={createMutation.isPending || !isValid}>
                {createMutation.isPending ? "Creating…" : "Create version"}
              </Button>
              <Link href={`/agents/${agentId}`} className="no-underline">
                <Button type="button" variant="tertiary">
                  Cancel
                </Button>
              </Link>
            </div>

            {configError && <p className="text-xs text-danger">{configError}</p>}
            {createMutation.isError && (
              <p className="text-xs text-danger">
                {createMutation.error instanceof ApiError
                  ? createMutation.error.message
                  : "Could not create this version."}
              </p>
            )}
          </form>
        </Card>
      </div>
    </AppShell>
  );
}
