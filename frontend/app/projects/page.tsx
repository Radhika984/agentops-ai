"use client";

import { useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../components/AppShell";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { TextInput } from "../components/ui/Input";
import { Skeleton } from "../components/ui/Skeleton";
import { ArrowRightIcon, EvaluationMark, ProjectsIcon, SearchIcon } from "../components/ui/icons";
import { PageHeader } from "../components/ui/PageHeader";
import { ApiError, clearToken, createProject, listAgents, listProjects } from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

export default function ProjectsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const checkedAuth = useRequireAuth();
  const [name, setName] = useState("");
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [search, setSearch] = useState("");

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
    enabled: checkedAuth,
  });

  // Same per-project fan-out agents/page.tsx already performs (ProjectRead
  // itself carries no agent count — there is no account-wide "count
  // agents per project" endpoint) — real counts, not a new capability.
  const agentCountsQuery = useQuery({
    queryKey: ["projects-agent-counts", (projectsQuery.data ?? []).map((p) => p.id).join(",")],
    queryFn: async (): Promise<Record<string, number>> => {
      const projects = projectsQuery.data ?? [];
      const entries = await Promise.all(
        projects.map(async (p) => [p.id, (await listAgents(p.id)).length] as const),
      );
      return Object.fromEntries(entries);
    },
    enabled: checkedAuth && projectsQuery.data !== undefined,
  });

  const createMutation = useMutation({
    mutationFn: () => createProject(name),
    onSuccess: () => {
      setName("");
      setIsCreateOpen(false);
      queryClient.invalidateQueries({ queryKey: ["projects"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
  });

  function handleCreate(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    createMutation.mutate();
  }

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  // Client-side filter over the already-fetched project list — there is
  // no search endpoint for this list view (the global header search
  // covers cross-entity lookup separately), so this narrows real,
  // already-loaded data rather than inventing server-side search here.
  const filteredProjects = useMemo(() => {
    const all = projectsQuery.data ?? [];
    const q = search.trim().toLowerCase();
    if (!q) return all;
    return all.filter(
      (p) => p.name.toLowerCase().includes(q) || (p.description ?? "").toLowerCase().includes(q),
    );
  }, [projectsQuery.data, search]);

  if (!checkedAuth) return null;

  return (
    <AppShell onLogout={handleLogout}>
      <div className="animate-fade-in-up mx-auto w-full max-w-5xl px-4 py-7 md:px-8">
        <PageHeader
          title="Projects"
          description="Manage and evaluate your AI agent workspaces."
          action={
            <Button variant="primary" onClick={() => setIsCreateOpen((v) => !v)}>
              + New project
            </Button>
          }
        />

        {projectsQuery.data && projectsQuery.data.length > 0 && (
          <div className="mt-5">
            <span className="relative flex max-w-xs items-center">
              <span className="pointer-events-none absolute left-3 text-ink-3">
                <SearchIcon />
              </span>
              <TextInput
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search projects…"
                className="pl-9"
                aria-label="Search projects"
              />
            </span>
          </div>
        )}

        {isCreateOpen && (
          <Card className="animate-fade-in-up mt-5" elevation="raised">
            <form onSubmit={handleCreate} className="flex flex-col gap-3 sm:flex-row sm:items-end">
              <label className="flex flex-1 flex-col gap-1.5 text-sm font-medium text-ink-2">
                Project name
                <TextInput
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Support triage agent"
                  autoFocus
                />
              </label>
              <Button
                type="submit"
                variant="primary"
                disabled={createMutation.isPending || !name.trim()}
              >
                {createMutation.isPending ? "Creating…" : "Create project"}
              </Button>
            </form>

            {createMutation.isError && (
              <p className="mt-3 text-sm text-danger">
                {createMutation.error instanceof ApiError
                  ? createMutation.error.message
                  : "Could not create project."}
              </p>
            )}
          </Card>
        )}

        <div className="mt-7">
          {projectsQuery.isLoading && (
            <div className="flex flex-col gap-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-14" />
              ))}
            </div>
          )}

          {projectsQuery.isError && (
            <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              {projectsQuery.error instanceof ApiError
                ? projectsQuery.error.message
                : "Could not load projects."}
            </p>
          )}

          {projectsQuery.data && projectsQuery.data.length === 0 && (
            <EmptyState
              icon={<EvaluationMark />}
              title="No evaluation projects yet"
              description="Create a workspace to start running and evaluating an AI-agent workflow."
              action={
                <Button variant="primary" onClick={() => setIsCreateOpen(true)}>
                  + Create your first project
                </Button>
              }
            />
          )}

          {projectsQuery.data &&
            projectsQuery.data.length > 0 &&
            filteredProjects.length === 0 && (
              <EmptyState
                title="No projects match your search"
                description={`Nothing found for "${search}". Try a different name or clear the search.`}
              />
            )}

          {/* Scannable rows, not a card grid (§14/§22) — a project is a
              workspace, not a decorative tile; ownership/agent-count/
              recency read left-to-right in one glance across many rows. */}
          {filteredProjects.length > 0 && (
            <Card elevation="raised" padded={false} className="overflow-hidden">
              <ul className="flex flex-col divide-y divide-line">
                {filteredProjects.map((project) => {
                  const agentCount = agentCountsQuery.data?.[project.id];
                  return (
                    <li key={project.id}>
                      <Link
                        href={`/projects/${project.id}/chat`}
                        className="group flex items-center gap-3 px-5 py-3.5 no-underline transition-colors duration-150 hover:bg-surface-2"
                      >
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent">
                          <ProjectsIcon />
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold text-ink">{project.name}</p>
                          <p className="truncate text-xs text-ink-3">
                            {project.description || "No description yet"}
                          </p>
                        </div>
                        <span className="hidden shrink-0 text-xs text-ink-3 sm:block">
                          {agentCount !== undefined ? `${agentCount} agent${agentCount === 1 ? "" : "s"}` : "—"}
                        </span>
                        <span className="hidden shrink-0 text-xs text-ink-3 md:block">
                          Updated {new Date(project.updated_at).toLocaleDateString()}
                        </span>
                        <ArrowRightIcon className="shrink-0 text-ink-3 opacity-0 transition-all duration-150 group-hover:translate-x-0.5 group-hover:text-accent group-hover:opacity-100" />
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </AppShell>
  );
}
