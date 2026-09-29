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
import { ApiError, clearToken, createProject, listProjects } from "../lib/api";
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
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold tracking-tight text-ink">Projects</h1>
            <p className="mt-1.5 text-sm text-ink-2">
              Manage and evaluate your AI agent workspaces.
            </p>
          </div>
          <Button variant="primary" onClick={() => setIsCreateOpen((v) => !v)}>
            + New project
          </Button>
        </div>

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
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-28" />
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

          {filteredProjects.length > 0 && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {filteredProjects.map((project, index) => (
                <Link key={project.id} href={`/projects/${project.id}/chat`} className="no-underline">
                  <Card
                    elevation="raised"
                    className="group glow-hover animate-fade-in-up relative h-full overflow-hidden p-5 transition-transform duration-200 hover:-translate-y-1"
                    style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }}
                  >
                    <span
                      className="absolute top-0 left-0 h-full w-0.75 bg-linear-to-b from-accent to-accent/30"
                      aria-hidden="true"
                    />
                    <span
                      className="pointer-events-none absolute -top-10 -left-10 h-32 w-32 rounded-full bg-accent/10 opacity-0 blur-2xl transition-opacity duration-300 group-hover:opacity-100"
                      aria-hidden="true"
                    />
                    <div className="relative flex items-start justify-between">
                      <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-accent-soft text-accent ring-1 ring-accent/15 transition-transform duration-200 group-hover:scale-105">
                        <ProjectsIcon />
                      </span>
                      <span
                        className="text-ink-3 opacity-0 transition-all duration-200 group-hover:translate-x-0.5 group-hover:text-accent group-hover:opacity-100"
                        aria-hidden="true"
                      >
                        <ArrowRightIcon />
                      </span>
                    </div>
                    <p className="relative mt-3.5 truncate text-[15px] font-semibold text-ink">
                      {project.name}
                    </p>
                    <p className="relative mt-1 line-clamp-2 min-h-[2.5em] text-xs text-ink-3">
                      {project.description || "No description yet"}
                    </p>
                    <div className="relative mt-3.5 flex items-center justify-between border-t border-line pt-3 text-[11px] text-ink-3">
                      <span>Created {new Date(project.created_at).toLocaleDateString()}</span>
                      <span>Updated {new Date(project.updated_at).toLocaleDateString()}</span>
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
