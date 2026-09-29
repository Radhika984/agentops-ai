"use client";

import { useRouter } from "next/navigation";
import { AppShell } from "../components/AppShell";
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
        <h1 className="text-3xl font-bold tracking-tight text-ink">Evaluation</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          Every test case result across your account, most recent first.
        </p>
        <ResultsTable
          emptyTitle="No evaluation results yet"
          emptyDescription="Run a test suite to see evaluated test case results here."
        />
      </div>
    </AppShell>
  );
}
