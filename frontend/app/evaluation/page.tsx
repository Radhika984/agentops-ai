"use client";

import { useRouter } from "next/navigation";
import { AppShell } from "../components/AppShell";
import { PageHeader } from "../components/ui/PageHeader";
import { ResultsTable } from "../components/ResultsTable";
import { clearToken } from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

export default function EvaluationPage() {
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  return (
    <AppShell onLogout={handleLogout}>
      <div className="animate-fade-in-up mx-auto w-full max-w-5xl px-4 py-7 md:px-8">
        <PageHeader
          title="Evaluation"
          description="Every test case result across your account, most recent first — open one to see EXPECTED vs. OBSERVED and exactly what differed."
        />
        <ResultsTable
          emptyTitle="No evaluation results yet"
          emptyDescription="Run a test suite to see evaluated test case results here."
        />
      </div>
    </AppShell>
  );
}
