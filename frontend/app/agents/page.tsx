"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../components/AppShell";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Field } from "../components/ui/Input";
import { SelectField } from "../components/ui/Select";
import { Skeleton } from "../components/ui/Skeleton";
import { AgentIcon, ArrowRightIcon } from "../components/ui/icons";
import {
  ApiError,
  clearToken,
  createAgent,
  listAgents,
  listProjects,
  type AgentRead,
  type ProjectRead,
} from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

const textareaClasses =
  "w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3 transition-colors duration-150 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/10";

interface AgentWithProject {
  agent: AgentRead;
  project: ProjectRead;
}

export default function AgentsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const checkedAuth = useRequireAuth();

  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [projectId, setProjectId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
    enabled: checkedAuth,
  });

  // Agents belong to a project (backend/app/api/v1/agents.py requires
  // project_id on both create and list — there is no cross-project list
  // endpoint), so this flattens every project's agents into one real list
  // rather than inventing a "list all agents" call that doesn't exist.
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

  const createMutation = useMutation({
    mutationFn: () =>
      createAgent({ project_id: projectId, name, description: description.trim() || undefined }),
    onSuccess: (agent) => {
      queryClient.invalidateQueries({ queryKey: ["agents-all"] });
      router.push(`/agents/${agent.id}`);
    },
  });

  function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!projectId || !name.trim() || createMutation.isPending) return;
    createMutation.mutate();
  }

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const projects = projectsQuery.data ?? [];
  const hasProjects = projects.length > 0;
  const agents = agentsQuery.data ?? [];
  const isLoading = projectsQuery.isLoading || (projectsQuery.data !== undefined && agentsQuery.isLoading);
  const loadError = agentsQuery.isError ? agentsQuery.error : projectsQuery.isError ? projectsQuery.error : null;

  return (
    <AppShell onLogout={handleLogout}>
      <div className="animate-fade-in-up mx-auto w-full max-w-5xl px-4 py-7 md:px-8">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-ink">Agents</h1>
            <p className="mt-1.5 text-sm text-ink-2">
              Registered Systems Under Test — connect an agent, create versions, and run test
              invocations.
            </p>
          </div>
          {hasProjects && (
            <Button variant="primary" onClick={() => setIsCreateOpen((v) => !v)}>
              + New agent
            </Button>
          )}
        </div>

        {isCreateOpen && hasProjects && (
          <Card className="mt-5" elevation="raised">
            <form onSubmit={handleCreate} className="flex flex-col gap-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <SelectField
                  label="Project"
                  value={projectId}
                  onChange={(e) => setProjectId(e.target.value)}
                  required
                >
                  <option value="" disabled>
                    Select a project…
                  </option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </SelectField>
                <Field
                  label="Agent name"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Support triage agent"
                  autoFocus
                />
              </div>
              <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
                Description (optional)
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What this agent does"
                  rows={2}
                  className={textareaClasses}
                />
              </label>
              <div>
                <Button
                  type="submit"
                  variant="primary"
                  disabled={createMutation.isPending || !projectId || !name.trim()}
                >
                  {createMutation.isPending ? "Creating…" : "Create agent"}
                </Button>
              </div>
              {createMutation.isError && (
                <p className="text-sm text-danger">
                  {createMutation.error instanceof ApiError
                    ? createMutation.error.message
                    : "Could not create agent."}
                </p>
              )}
            </form>
          </Card>
        )}

        <div className="mt-7">
          {isLoading && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-28" />
              ))}
            </div>
          )}

          {loadError && (
            <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              {loadError instanceof ApiError ? loadError.message : "Could not load agents."}
            </p>
          )}

          {!isLoading && !loadError && !hasProjects && (
            <EmptyState
              icon={<AgentIcon />}
              title="Create a project first"
              description="Agents belong to a project — create a project before registering an agent."
              action={
                <Link href="/projects" className="no-underline">
                  <Button variant="primary">Go to projects</Button>
                </Link>
              }
            />
          )}

          {!isLoading && !loadError && hasProjects && agents.length === 0 && (
            <EmptyState
              icon={<AgentIcon />}
              title="No agents yet"
              description="Register the agent you want to evaluate to get started."
              action={
                <Button variant="primary" onClick={() => setIsCreateOpen(true)}>
                  + Register your first agent
                </Button>
              }
            />
          )}

          {agents.length > 0 && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {agents.map(({ agent, project }, index) => (
                <Link key={agent.id} href={`/agents/${agent.id}`} className="no-underline">
                  <Card
                    elevation="raised"
                    className="group glow-hover animate-fade-in-up relative h-full overflow-hidden transition-transform duration-200 hover:-translate-y-1"
                    style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }}
                  >
                    <span
                      className="absolute top-0 left-0 h-full w-1 bg-accent/70"
                      aria-hidden="true"
                    />
                    <div className="flex items-start justify-between">
                      <span className="flex h-9 w-9 items-center justify-center rounded-md bg-accent-soft text-accent">
                        <AgentIcon />
                      </span>
                      <Badge tone={agent.is_enabled ? "success" : "neutral"}>
                        {agent.is_enabled ? "enabled" : "disabled"}
                      </Badge>
                    </div>
                    <p className="mt-3 truncate text-sm font-semibold text-ink">{agent.name}</p>
                    <p className="mt-1 line-clamp-2 min-h-[2.5em] text-xs text-ink-3">
                      {agent.description || "No description yet"}
                    </p>
                    <div className="mt-3 flex items-center justify-between gap-2 border-t border-line pt-2.5 text-xs text-ink-3">
                      <span className="truncate">{project.name}</span>
                      <ArrowRightIcon className="shrink-0 text-ink-3 opacity-0 transition-all duration-150 group-hover:translate-x-0.5 group-hover:text-accent group-hover:opacity-100" />
                    </div>
                  </Card>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </AppShell>
  );
}
