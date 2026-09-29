"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "../components/AppShell";
import { Badge, type Tone } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { RunsIcon } from "../components/ui/icons";
import { ApiError, clearToken, listAllSuiteRuns } from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

const PAGE_SIZE = 20;

const VERDICT_TONE: Record<string, Tone> = { PASS: "success", FAIL: "danger", INCONCLUSIVE: "warning" };
const STATUS_TONE: Record<string, Tone> = {
  completed: "success",
  failed: "danger",
  running: "accent",
  pending: "neutral",
  cancelling: "warning",
};

export default function AllRunsPage() {
  const router = useRouter();
  const checkedAuth = useRequireAuth();
  const [offset, setOffset] = useState(0);

  const runsQuery = useQuery({
    queryKey: ["suite-runs", "all", offset],
    queryFn: () => listAllSuiteRuns(PAGE_SIZE, offset),
    enabled: checkedAuth,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const total = runsQuery.data?.total ?? 0;
  const hasNext = offset + PAGE_SIZE < total;
  const hasPrev = offset > 0;

  return (
    <AppShell onLogout={handleLogout}>
      <div className="animate-fade-in-up mx-auto w-full max-w-5xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Runs</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          Every suite run across your account, most recent first.
        </p>

        <Card elevation="raised" padded={false} className="mt-7 overflow-hidden">
          {runsQuery.isLoading && (
            <div className="flex flex-col gap-2 p-5">
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </div>
          )}

          {runsQuery.isError && (
            <p className="m-5 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              {runsQuery.error instanceof ApiError ? runsQuery.error.message : "Could not load runs."}
            </p>
          )}

          {runsQuery.data && runsQuery.data.items.length === 0 && (
            <div className="p-5">
              <EmptyState
                icon={<RunsIcon />}
                title="No suite runs yet"
                description="Run a test suite against an agent version to see it here."
              />
            </div>
          )}

          {runsQuery.data && runsQuery.data.items.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[700px] text-left text-sm">
                <thead>
                  <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-3">
                    <th className="px-5 py-2.5 font-medium">Project</th>
                    <th className="px-3 py-2.5 font-medium">Agent</th>
                    <th className="px-3 py-2.5 font-medium">Suite</th>
                    <th className="px-3 py-2.5 font-medium">Version</th>
                    <th className="px-3 py-2.5 font-medium">Status</th>
                    <th className="px-3 py-2.5 font-medium">Verdict</th>
                    <th className="px-5 py-2.5 text-right font-medium">Completed</th>
                  </tr>
                </thead>
                <tbody>
                  {runsQuery.data.items.map((run) => {
                    const total = run.pass_count + run.fail_count + run.inconclusive_count;
                    const verdict = run.verdict;
                    return (
                      <tr
                        key={run.id}
                        className="cursor-pointer border-b border-line transition-colors duration-150 last:border-b-0 hover:bg-surface-2"
                        onClick={() =>
                          router.push(
                            `/agents/${run.agent_id}/test-suites/${run.suite_id}/runs/${run.id}`,
                          )
                        }
                      >
                        <td className="max-w-[140px] truncate px-5 py-2.5 text-ink">
                          {run.project_name}
                        </td>
                        <td className="max-w-[140px] truncate px-3 py-2.5 text-ink-2">
                          {run.agent_name}
                        </td>
                        <td className="max-w-[140px] truncate px-3 py-2.5 text-ink-2">
                          {run.suite_name}
                        </td>
                        <td className="px-3 py-2.5">
                          <code className="rounded bg-surface-2 px-1.5 py-0.5 text-xs text-ink-2">
                            {run.version_label}
                          </code>
                        </td>
                        <td className="px-3 py-2.5">
                          <Badge tone={STATUS_TONE[run.status] ?? "neutral"}>{run.status}</Badge>
                        </td>
                        <td className="px-3 py-2.5">
                          {verdict ? (
                            <Badge tone={VERDICT_TONE[verdict] ?? "neutral"}>
                              {verdict}
                              {total > 0 ? ` (${total})` : ""}
                            </Badge>
                          ) : (
                            <span className="text-ink-3">—</span>
                          )}
                        </td>
                        <td className="px-5 py-2.5 text-right text-xs text-ink-3">
                          {run.completed_at
                            ? new Date(run.completed_at).toLocaleString()
                            : "In progress"}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {total > PAGE_SIZE && (
          <div className="mt-4 flex items-center justify-between text-sm text-ink-3">
            <span>
              {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
            </span>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={!hasPrev}
                onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={!hasNext}
                onClick={() => setOffset(offset + PAGE_SIZE)}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}
