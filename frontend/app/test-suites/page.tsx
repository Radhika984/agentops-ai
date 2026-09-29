"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "../components/AppShell";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { ArrowRightIcon, TestSuitesIcon } from "../components/ui/icons";
import { ApiError, clearToken, listAllTestSuites } from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

export default function AllTestSuitesPage() {
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  const suitesQuery = useQuery({
    queryKey: ["test-suites", "all"],
    queryFn: listAllTestSuites,
    enabled: checkedAuth,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  return (
    <AppShell onLogout={handleLogout}>
      <div className="animate-fade-in-up mx-auto w-full max-w-5xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Test Suites</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          Every test suite across your agents — pick one to view its test cases and runs.
        </p>

        <div className="mt-7">
          {suitesQuery.isLoading && (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-24" />
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
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {suitesQuery.data.map((suite, index) => (
                <Link
                  key={suite.id}
                  href={`/agents/${suite.agent_id}/test-suites/${suite.id}`}
                  className="no-underline"
                >
                  <Card
                    elevation="raised"
                    className="group glow-hover animate-fade-in-up relative h-full overflow-hidden transition-transform duration-200 hover:-translate-y-1"
                    style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }}
                  >
                    <div className="flex items-start justify-between">
                      <span className="flex h-9 w-9 items-center justify-center rounded-md bg-accent-soft text-accent">
                        <TestSuitesIcon />
                      </span>
                      <ArrowRightIcon className="text-ink-3 opacity-0 transition-all duration-150 group-hover:translate-x-0.5 group-hover:text-accent group-hover:opacity-100" />
                    </div>
                    <p className="mt-3 truncate text-sm font-semibold text-ink">{suite.name}</p>
                    <p className="mt-2 border-t border-line pt-2.5 text-xs text-ink-3">
                      Created {new Date(suite.created_at).toLocaleDateString()}
                    </p>
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
