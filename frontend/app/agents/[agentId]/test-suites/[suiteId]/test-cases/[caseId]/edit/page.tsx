"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../../../../../../../components/AppShell";
import { Card } from "../../../../../../../components/ui/Card";
import { Skeleton } from "../../../../../../../components/ui/Skeleton";
import { ChevronLeftIcon } from "../../../../../../../components/ui/icons";
import { TestCaseForm } from "../../../../../../../components/TestCaseForm";
import { ApiError, clearToken, getTestCase } from "../../../../../../../lib/api";
import { useRequireAuth } from "../../../../../../../lib/useRequireAuth";

export default function EditTestCasePage() {
  const { agentId, suiteId, caseId } = useParams<{ agentId: string; suiteId: string; caseId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const checkedAuth = useRequireAuth();

  const caseQuery = useQuery({
    queryKey: ["test-case", suiteId, caseId],
    queryFn: () => getTestCase(suiteId, caseId),
    enabled: checkedAuth,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  function goToSuite() {
    router.push(`/agents/${agentId}/test-suites/${suiteId}`);
  }

  function handleSuccess() {
    queryClient.invalidateQueries({ queryKey: ["test-cases", suiteId] });
    goToSuite();
  }

  if (!checkedAuth) return null;

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href={`/agents/${agentId}/test-suites/${suiteId}`}
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        Test suite
      </Link>
      <p className="text-sm font-semibold text-ink">Edit test case</p>
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-3xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Edit test case</h1>

        {caseQuery.isLoading && (
          <div className="mt-6 flex flex-col gap-3">
            <Skeleton className="h-10" />
            <Skeleton className="h-24" />
          </div>
        )}

        {caseQuery.isError && (
          <p className="mt-6 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {caseQuery.error instanceof ApiError ? caseQuery.error.message : "Could not load this test case."}
          </p>
        )}

        {caseQuery.data && (
          <Card className="mt-6" elevation="raised">
            <TestCaseForm
              suiteId={suiteId}
              initialCase={caseQuery.data}
              onSuccess={handleSuccess}
              onCancel={goToSuite}
            />
          </Card>
        )}
      </div>
    </AppShell>
  );
}
