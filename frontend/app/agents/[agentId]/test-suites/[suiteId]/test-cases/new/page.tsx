"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../../../../../../components/AppShell";
import { Card } from "../../../../../../components/ui/Card";
import { ChevronLeftIcon } from "../../../../../../components/ui/icons";
import { TestCaseForm } from "../../../../../../components/TestCaseForm";
import { clearToken } from "../../../../../../lib/api";
import { useRequireAuth } from "../../../../../../lib/useRequireAuth";

export default function CreateTestCasePage() {
  const { agentId, suiteId } = useParams<{ agentId: string; suiteId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const checkedAuth = useRequireAuth();

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
      <p className="text-sm font-semibold text-ink">New test case</p>
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-3xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">New test case</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          Define what a correct response looks like — at least one ground-truth mechanism is
          required.
        </p>

        <Card className="mt-6" elevation="raised">
          <TestCaseForm suiteId={suiteId} onSuccess={handleSuccess} onCancel={goToSuite} />
        </Card>
      </div>
    </AppShell>
  );
}
