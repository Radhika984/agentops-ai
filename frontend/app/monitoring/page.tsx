"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "../components/AppShell";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Disclosure } from "../components/ui/CodeDisclosure";
import { EmptyState } from "../components/ui/EmptyState";
import { Field } from "../components/ui/Input";
import { Skeleton } from "../components/ui/Skeleton";
import { MonitoringIcon } from "../components/ui/icons";
import {
  ApiError,
  clearToken,
  listAgentVersions,
  listAgents,
  listProjects,
  type AgentRead,
  type AgentVersionRead,
  type ProjectRead,
} from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

interface AgentWithProject {
  agent: AgentRead;
  project: ProjectRead;
}

interface VersionWithContext {
  version: AgentVersionRead;
  agent: AgentRead;
  project: ProjectRead;
}

/**
 * Monitoring entry point. There is no single "list every Agent Version I
 * own" endpoint (backend/app/api/v1/agents.py scopes versions under one
 * agent at a time), so this fans out through the same real endpoints
 * agents/page.tsx already uses (listProjects → listAgents per project),
 * one level further (listAgentVersions per agent) — a real picker built
 * from real data, not a fabricated list. Pasting an id directly stays
 * available as a fallback for a version this account can't otherwise
 * enumerate (e.g. one only ever created through the API).
 */
export default function MonitoringEntryPage() {
  const router = useRouter();
  const checkedAuth = useRequireAuth();
  const [versionId, setVersionId] = useState("");

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
    enabled: checkedAuth,
  });

  const agentsQuery = useQuery({
    queryKey: ["agents-all", (projectsQuery.data ?? []).map((p) => p.id).join(",")],
    queryFn: async (): Promise<AgentWithProject[]> => {
      const projects = projectsQuery.data ?? [];
      const perProject = await Promise.all(
        projects.map(async (project) => {
          const agents = await listAgents(project.id);
          return agents.map((agent) => ({ agent, project }));
        }),
      );
      return perProject.flat();
    },
    enabled: checkedAuth && projectsQuery.data !== undefined,
  });

  const versionsQuery = useQuery({
    queryKey: ["agent-versions-all", (agentsQuery.data ?? []).map((a) => a.agent.id).join(",")],
    queryFn: async (): Promise<VersionWithContext[]> => {
      const withProject = agentsQuery.data ?? [];
      const perAgent = await Promise.all(
        withProject.map(async ({ agent, project }) => {
          const versions = await listAgentVersions(agent.id);
          return versions.map((version) => ({ version, agent, project }));
        }),
      );
      return perAgent.flat();
    },
    enabled: checkedAuth && agentsQuery.data !== undefined,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  function handleManualSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = versionId.trim();
    if (!trimmed) return;
    router.push(`/agent-versions/${trimmed}/monitoring`);
  }

  if (!checkedAuth) return null;

  const isLoading =
    projectsQuery.isLoading ||
    (projectsQuery.data !== undefined && agentsQuery.isLoading) ||
    (agentsQuery.data !== undefined && versionsQuery.isLoading);
  const loadError = versionsQuery.isError
    ? versionsQuery.error
    : agentsQuery.isError
      ? agentsQuery.error
      : projectsQuery.isError
        ? projectsQuery.error
        : null;
  const versions = versionsQuery.data ?? [];

  return (
    <AppShell onLogout={handleLogout}>
      <div className="animate-fade-in-up mx-auto w-full max-w-3xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Monitoring</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          Post-release execution evidence for an Agent Version — safety, tool trajectory, schema,
          latency and grounding evidence evaluated from what the agent actually reported, plus any
          regression-candidate test cases proposed from a real failure.
        </p>

        <div className="mt-6">
          {isLoading && (
            <div className="flex flex-col gap-3">
              <Skeleton className="h-16" />
              <Skeleton className="h-16" />
            </div>
          )}

          {loadError && (
            <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              {loadError instanceof ApiError ? loadError.message : "Could not load agent versions."}
            </p>
          )}

          {!isLoading && !loadError && versions.length === 0 && (
            <EmptyState
              icon={<MonitoringIcon />}
              title="No agent versions yet"
              description="Create an Agent Version from an agent's page to see its monitoring here."
              action={
                <Link href="/agents" className="no-underline">
                  <Button variant="primary">Go to Agents</Button>
                </Link>
              }
            />
          )}

          {!isLoading && !loadError && versions.length > 0 && (
            <div className="flex flex-col gap-2">
              {versions.map(({ version, agent, project }) => (
                <Link
                  key={version.id}
                  href={`/agent-versions/${version.id}/monitoring`}
                  className="no-underline"
                >
                  <Card
                    elevation="raised"
                    className="flex items-center justify-between gap-3 transition-all duration-150 hover:-translate-y-0.5 hover:shadow-md"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="truncate text-sm font-semibold text-ink">{agent.name}</p>
                        <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-ink-2">
                          {version.label}
                        </code>
                        {version.is_baseline && <Badge tone="accent">baseline</Badge>}
                      </div>
                      <p className="mt-1 truncate text-xs text-ink-3">
                        {project.name} · {version.adapter_type}
                      </p>
                    </div>
                  </Card>
                </Link>
              ))}
            </div>
          )}
        </div>

        <div className="mt-6 border-t border-line pt-4">
          <Disclosure summary="Open an Agent Version by ID instead">
            <form onSubmit={handleManualSubmit} className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <Field
                label="Agent Version ID"
                value={versionId}
                onChange={(e) => setVersionId(e.target.value)}
                placeholder="e.g. 3fa85f64-5717-4562-b3fc-2c963f66afa6"
                className="flex-1 font-mono"
              />
              <Button type="submit" variant="secondary" disabled={!versionId.trim()}>
                View monitoring
              </Button>
            </form>
          </Disclosure>
        </div>
      </div>
    </AppShell>
  );
}
