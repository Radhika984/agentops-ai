"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AppShell } from "../../../../../components/AppShell";
import { Badge } from "../../../../../components/ui/Badge";
import { Button } from "../../../../../components/ui/Button";
import { Card } from "../../../../../components/ui/Card";
import { Field } from "../../../../../components/ui/Input";
import { SelectField } from "../../../../../components/ui/Select";
import { ChevronLeftIcon } from "../../../../../components/ui/icons";
import {
  ApiError,
  clearToken,
  createSuiteRun,
  listAgentVersions,
} from "../../../../../lib/api";
import { useRequireAuth } from "../../../../../lib/useRequireAuth";

const MAX_CONCURRENCY_LIMIT = 5;

export default function RunSuitePage() {
  const { agentId, suiteId } = useParams<{ agentId: string; suiteId: string }>();
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  const [agentVersionId, setAgentVersionId] = useState("");
  const [maxConcurrency, setMaxConcurrency] = useState("1");

  const versionsQuery = useQuery({
    queryKey: ["agent-versions", agentId],
    queryFn: () => listAgentVersions(agentId),
    enabled: checkedAuth,
  });

  const runMutation = useMutation({
    mutationFn: () =>
      createSuiteRun(suiteId, {
        agent_version_id: agentVersionId,
        max_concurrency: Number(maxConcurrency) || 1,
      }),
    onSuccess: (run) => {
      router.push(`/agents/${agentId}/test-suites/${suiteId}/runs/${run.id}`);
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!agentVersionId || runMutation.isPending) return;
    runMutation.mutate();
  }

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const versions = versionsQuery.data ?? [];

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href={`/agents/${agentId}/test-suites/${suiteId}`}
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        Test suite
      </Link>
      <p className="text-sm font-semibold text-ink">Run suite</p>
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-2xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Run suite</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          Executes every active test case in this suite against the selected Agent Version.
        </p>

        <Card className="mt-6" elevation="raised">
          {versionsQuery.isLoading && <p className="text-sm text-ink-3">Loading agent versions…</p>}

          {versionsQuery.isError && (
            <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              {versionsQuery.error instanceof ApiError
                ? versionsQuery.error.message
                : "Could not load agent versions."}
            </p>
          )}

          {versionsQuery.data && versions.length === 0 && (
            <div className="text-sm text-ink-2">
              This agent has no versions yet.{" "}
              <Link href={`/agents/${agentId}/versions/new`} className="text-accent no-underline hover:underline">
                Create one
              </Link>{" "}
              before running this suite.
            </div>
          )}

          {versions.length > 0 && (
            <form onSubmit={handleSubmit} className="flex flex-col gap-4">
              <SelectField
                label="Agent version"
                value={agentVersionId}
                onChange={(e) => setAgentVersionId(e.target.value)}
                required
              >
                <option value="" disabled>
                  Select a version…
                </option>
                {versions.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.label}
                    {v.is_baseline ? " (baseline)" : ""}
                  </option>
                ))}
              </SelectField>

              {agentVersionId && (
                <div>
                  {versions.find((v) => v.id === agentVersionId)?.is_baseline && (
                    <Badge tone="accent">baseline</Badge>
                  )}
                </div>
              )}

              <Field
                label={`Max concurrency (1–${MAX_CONCURRENCY_LIMIT})`}
                type="number"
                min={1}
                max={MAX_CONCURRENCY_LIMIT}
                value={maxConcurrency}
                onChange={(e) => setMaxConcurrency(e.target.value)}
                required
              />

              <div className="flex items-center gap-2">
                <Button type="submit" variant="primary" disabled={runMutation.isPending || !agentVersionId}>
                  {runMutation.isPending ? "Starting…" : "Run suite"}
                </Button>
                <Link href={`/agents/${agentId}/test-suites/${suiteId}`} className="no-underline">
                  <Button type="button" variant="tertiary">
                    Cancel
                  </Button>
                </Link>
              </div>

              {runMutation.isError && (
                <p className="text-xs text-danger">
                  {runMutation.error instanceof ApiError
                    ? runMutation.error.message
                    : "Could not start this suite run."}
                </p>
              )}
            </form>
          )}
        </Card>
      </div>
    </AppShell>
  );
}
