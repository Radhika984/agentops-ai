"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "../components/AppShell";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { ArrowRightIcon, TestSuitesIcon } from "../components/ui/icons";
import { PageHeader } from "../components/ui/PageHeader";
import { ApiError, clearToken, getAgent, listAllTestSuites, listTestCases } from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

export default function AllTestSuitesPage() {
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  const suitesQuery = useQuery({
    queryKey: ["test-suites", "all"],
    queryFn: listAllTestSuites,
    enabled: checkedAuth,
  });

  // TestSuiteRead carries neither a test-case count nor its agent's
  // name — both fetched here directly (listTestCases per suite, the
  // same call the suite detail page already makes; getAgent once per
  // distinct agent_id, deduplicated) rather than fabricated.
  const suiteIds = (suitesQuery.data ?? []).map((s) => s.id);
  const testCaseCountsQuery = useQuery({
    queryKey: ["test-suites-case-counts", suiteIds.join(",")],
    queryFn: async (): Promise<Record<string, number>> => {
      const entries = await Promise.all(
        suiteIds.map(async (id) => [id, (await listTestCases(id)).length] as const),
      );
      return Object.fromEntries(entries);
    },
    enabled: checkedAuth && suitesQuery.data !== undefined,
  });

  const agentIds = [...new Set((suitesQuery.data ?? []).map((s) => s.agent_id))];
  const agentNamesQuery = useQuery({
    queryKey: ["test-suites-agent-names", agentIds.join(",")],
    queryFn: async (): Promise<Record<string, string>> => {
      const entries = await Promise.all(agentIds.map(async (id) => [id, (await getAgent(id)).name] as const));
      return Object.fromEntries(entries);
    },
    enabled: checkedAuth && suitesQuery.data !== undefined,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  return (
    <AppShell onLogout={handleLogout}>
      <div className="animate-fade-in-up mx-auto w-full max-w-5xl px-4 py-7 md:px-8">
        <PageHeader
          title="Test Suites"
          description="Every test suite across your agents — pick one to view its test cases and runs."
        />

        <div className="mt-7">
          {suitesQuery.isLoading && (
            <div className="flex flex-col gap-2">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-14" />
              ))}
            </div>
          )}

          {suitesQuery.isError && (
            <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              {suitesQuery.error instanceof ApiError
                ? suitesQuery.error.message
                : "Could not load test suites."}
            </p>
          )}

          {suitesQuery.data && suitesQuery.data.length === 0 && (
            <EmptyState
              icon={<TestSuitesIcon />}
              title="No test suites yet"
              description="Create a test suite from an agent's page to start grouping test cases."
              action={
                <Link href="/agents" className="no-underline">
                  <span className="text-sm font-medium text-accent hover:text-accent-hover">
                    Go to Agents →
                  </span>
                </Link>
              }
            />
          )}

          {suitesQuery.data && suitesQuery.data.length > 0 && (
            <Card elevation="raised" padded={false} className="overflow-hidden">
              <ul className="flex flex-col divide-y divide-line">
                {suitesQuery.data.map((suite) => {
                  const caseCount = testCaseCountsQuery.data?.[suite.id];
                  const agentName = agentNamesQuery.data?.[suite.agent_id];
                  return (
                    <li key={suite.id}>
                      <Link
                        href={`/agents/${suite.agent_id}/test-suites/${suite.id}`}
                        className="group flex items-center gap-3 px-5 py-3.5 no-underline transition-colors duration-150 hover:bg-surface-2"
                      >
                        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-accent-soft text-accent">
                          <TestSuitesIcon />
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-semibold text-ink">{suite.name}</p>
                          <p className="truncate text-xs text-ink-3">{agentName ?? "—"}</p>
                        </div>
                        <span className="hidden shrink-0 text-xs text-ink-3 sm:block">
                          {caseCount !== undefined ? `${caseCount} test case${caseCount === 1 ? "" : "s"}` : "—"}
                        </span>
                        <span className="hidden shrink-0 text-xs text-ink-3 md:block">
                          Created {new Date(suite.created_at).toLocaleDateString()}
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
