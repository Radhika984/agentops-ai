"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../../components/AppShell";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { EmptyState } from "../../components/ui/EmptyState";
import { Section } from "../../components/ui/Section";
import { Skeleton } from "../../components/ui/Skeleton";
import { AgentIcon, ArrowRightIcon, ChevronLeftIcon, VerifyIcon, WarningIcon } from "../../components/ui/icons";
import {
  ApiError,
  clearToken,
  getAgent,
  listAgentVersions,
  listTestSuites,
  promoteBaseline,
  type AgentVersionRead,
} from "../../lib/api";
import { useRequireAuth } from "../../lib/useRequireAuth";

function ListValue({ values }: { values: string[] | null }) {
  if (!values || values.length === 0) return <span className="text-sm text-ink-3">—</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {values.map((v) => (
        <Badge key={v} tone="neutral">
          {v}
        </Badge>
      ))}
    </div>
  );
}

// BUG-004: a 403 (not this user's agent) or 404 (no such agent) are both
// terminal, well-understood outcomes — not a generic "something broke"
// error. Distinguishing them here (title/copy only) keeps the existing
// 403-vs-404 distinction the backend already enforces (see
// agent_service.py's _get_owned_agent, which raises NotFoundError before
// ever raising PermissionDeniedError) visible to the user, instead of
// collapsing both into the same unhelpful line the generic error path
// below still uses for everything else (5xx/network).
function AgentAccessError({ status }: { status: number }) {
  const isForbidden = status === 403;
  return (
    <EmptyState
      icon={<WarningIcon />}
      title={isForbidden ? "You don't have access to this agent" : "Agent not found"}
      description={
        isForbidden
          ? "This agent belongs to a different account. If you think this is a mistake, confirm you're signed in as the right user."
          : "This agent doesn't exist or may have been deleted."
      }
      action={
        <Link href="/agents" className="no-underline">
          <Button variant="primary">Back to Agents</Button>
        </Link>
      }
    />
  );
}

function VersionRow({ agentId, version }: { agentId: string; version: AgentVersionRead }) {
  const [confirming, setConfirming] = useState(false);
  const queryClient = useQueryClient();

  const promoteMutation = useMutation({
    mutationFn: () => promoteBaseline(agentId, version.id),
    onSuccess: () => {
      setConfirming(false);
      queryClient.invalidateQueries({ queryKey: ["agent-versions", agentId] });
    },
  });

  return (
    <Card elevation="raised">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-semibold text-ink">{version.label}</p>
            {version.is_baseline && <Badge tone="accent">baseline</Badge>}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
            <Badge tone="neutral">{version.adapter_type}</Badge>
            <span>Observability level {version.observability_level}</span>
            <span>· Created {new Date(version.created_at).toLocaleDateString()}</span>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Link href={`/agents/${agentId}/versions/${version.id}/test-invoke`} className="no-underline">
            <Button variant="secondary" size="sm">
              Test invoke
            </Button>
          </Link>
          <Link href={`/agent-versions/${version.id}/monitoring`} className="no-underline">
            <Button variant="secondary" size="sm">
              Monitoring
            </Button>
          </Link>
          {!version.is_baseline && !confirming && (
            <Button variant="secondary" size="sm" onClick={() => setConfirming(true)}>
              Promote to baseline
            </Button>
          )}
        </div>
      </div>

      {confirming && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <span className="text-xs text-ink-2">Set &ldquo;{version.label}&rdquo; as the baseline version?</span>
          <Button
            variant="primary"
            size="sm"
            onClick={() => promoteMutation.mutate()}
            disabled={promoteMutation.isPending}
          >
            {promoteMutation.isPending ? "Promoting…" : "Confirm"}
          </Button>
          <Button
            variant="tertiary"
            size="sm"
            onClick={() => setConfirming(false)}
            disabled={promoteMutation.isPending}
          >
            Cancel
          </Button>
        </div>
      )}

      {promoteMutation.isError && (
        <p className="mt-2 text-xs text-danger">
          {promoteMutation.error instanceof ApiError
            ? promoteMutation.error.message
            : "Could not promote this version."}
        </p>
      )}
    </Card>
  );
}

export default function AgentDetailPage() {
  const { agentId } = useParams<{ agentId: string }>();
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  const agentQuery = useQuery({
    queryKey: ["agent", agentId],
    queryFn: () => getAgent(agentId),
    enabled: checkedAuth,
  });

  const versionsQuery = useQuery({
    queryKey: ["agent-versions", agentId],
    queryFn: () => listAgentVersions(agentId),
    enabled: checkedAuth,
  });

  const suitesQuery = useQuery({
    queryKey: ["test-suites", agentId],
    queryFn: () => listTestSuites(agentId),
    enabled: checkedAuth,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const agent = agentQuery.data;
  const versions = versionsQuery.data ?? [];
  const suites = suitesQuery.data ?? [];

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href="/agents"
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        Agents
      </Link>
      {agent && <p className="truncate text-sm font-semibold text-ink">{agent.name}</p>}
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-3xl px-4 py-7 md:px-8">
        {agentQuery.isLoading && (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-40" />
          </div>
        )}

        {agentQuery.isError &&
          (agentQuery.error instanceof ApiError && (agentQuery.error.status === 403 || agentQuery.error.status === 404) ? (
            <AgentAccessError status={agentQuery.error.status} />
          ) : (
            <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              {agentQuery.error instanceof ApiError ? agentQuery.error.message : "Could not load this agent."}
            </p>
          ))}

        {agent && (
          <>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2.5">
                  <h1 className="text-3xl font-bold tracking-tight text-ink">{agent.name}</h1>
                  <Badge tone={agent.is_enabled ? "success" : "neutral"}>
                    {agent.is_enabled ? "enabled" : "disabled"}
                  </Badge>
                </div>
                <p className="mt-1.5 max-w-2xl text-sm text-ink-2">
                  {agent.description || "No description yet"}
                </p>
              </div>
              <Link href={`/agents/${agentId}/edit`} className="no-underline">
                <Button variant="secondary">Edit agent</Button>
              </Link>
            </div>

            <div className="mt-6 overflow-hidden rounded-lg border border-line bg-surface-elevated shadow-md">
              <Section label="Default evaluation contract">
                <dl className="grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs text-ink-3">Expected behavior</dt>
                    <dd className="mt-1">
                      <ListValue values={agent.default_expected_behavior} />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-3">Forbidden behavior</dt>
                    <dd className="mt-1">
                      <ListValue values={agent.default_forbidden_behavior} />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-3">Allowed tools</dt>
                    <dd className="mt-1">
                      <ListValue values={agent.default_allowed_tools} />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-3">Required tools</dt>
                    <dd className="mt-1">
                      <ListValue values={agent.default_required_tools} />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-3">Latency threshold</dt>
                    <dd className="mt-1 text-sm text-ink">
                      {agent.default_latency_threshold_ms !== null
                        ? `${agent.default_latency_threshold_ms}ms`
                        : "—"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-3">Default timeout</dt>
                    <dd className="mt-1 text-sm text-ink">{agent.default_timeout_ms}ms</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-ink-3">Min call interval</dt>
                    <dd className="mt-1 text-sm text-ink">{agent.min_call_interval_ms}ms</dd>
                  </div>
                </dl>
                {agent.default_output_schema && (
                  <div className="mt-3">
                    <p className="text-xs text-ink-3">Output schema</p>
                    <pre className="mt-1 overflow-x-auto rounded bg-surface-2 px-2.5 py-2 font-mono text-[11px] whitespace-pre-wrap text-ink-2">
                      {JSON.stringify(agent.default_output_schema, null, 2)}
                    </pre>
                  </div>
                )}
              </Section>
            </div>

            <div className="mt-7">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">Versions</p>
                <Link href={`/agents/${agentId}/versions/new`} className="no-underline">
                  <Button variant="primary" size="sm">
                    + New version
                  </Button>
                </Link>
              </div>

              <div className="mt-3 flex flex-col gap-3">
                {versionsQuery.isLoading && (
                  <>
                    <Skeleton className="h-20" />
                    <Skeleton className="h-20" />
                  </>
                )}

                {versionsQuery.isError && (
                  <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                    {versionsQuery.error instanceof ApiError
                      ? versionsQuery.error.message
                      : "Could not load versions."}
                  </p>
                )}

                {versionsQuery.data && versions.length === 0 && (
                  <EmptyState
                    icon={<AgentIcon />}
                    title="No versions yet"
                    description="Create a version to connect this agent to a real endpoint and start invoking it."
                    action={
                      <Link href={`/agents/${agentId}/versions/new`} className="no-underline">
                        <Button variant="primary">+ Create the first version</Button>
                      </Link>
                    }
                  />
                )}

                {versions.map((v) => (
                  <VersionRow key={v.id} agentId={agentId} version={v} />
                ))}
              </div>
            </div>

            <div className="mt-7">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">Test suites</p>
                <Link href={`/agents/${agentId}/test-suites/new`} className="no-underline">
                  <Button variant="primary" size="sm">
                    + New test suite
                  </Button>
                </Link>
              </div>

              <div className="mt-3 flex flex-col gap-3">
                {suitesQuery.isLoading && (
                  <>
                    <Skeleton className="h-16" />
                    <Skeleton className="h-16" />
                  </>
                )}

                {suitesQuery.isError && (
                  <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                    {suitesQuery.error instanceof ApiError
                      ? suitesQuery.error.message
                      : "Could not load test suites."}
                  </p>
                )}

                {suitesQuery.data && suites.length === 0 && (
                  <EmptyState
                    icon={<VerifyIcon />}
                    title="No test suites yet"
                    description="Create a test suite to start adding test cases for this agent."
                    action={
                      <Link href={`/agents/${agentId}/test-suites/new`} className="no-underline">
                        <Button variant="primary">+ Create the first test suite</Button>
                      </Link>
                    }
                  />
                )}

                {suites.map((suite) => (
                  <Link
                    key={suite.id}
                    href={`/agents/${agentId}/test-suites/${suite.id}`}
                    className="no-underline"
                  >
                    <Card
                      elevation="raised"
                      className="transition-all duration-150 hover:-translate-y-0.5 hover:shadow-md"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-ink">{suite.name}</p>
                          <p className="mt-1 text-xs text-ink-3">
                            Created {new Date(suite.created_at).toLocaleDateString()} · Updated{" "}
                            {new Date(suite.updated_at).toLocaleDateString()}
                          </p>
                        </div>
                        <ArrowRightIcon className="shrink-0 text-ink-3" />
                      </div>
                    </Card>
                  </Link>
                ))}
              </div>
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
