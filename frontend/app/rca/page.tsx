"use client";

import { useRouter } from "next/navigation";
import { AppShell } from "../components/AppShell";
import { ResultsTable } from "../components/ResultsTable";
import { clearToken } from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

export default function RcaPage() {
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
        <h1 className="text-3xl font-bold tracking-tight text-ink">RCA</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          Failed and inconclusive results across your account — open one to run root-cause
          analysis.
        </p>
        <ResultsTable
          verdicts={["FAIL", "INCONCLUSIVE"]}
          emptyTitle="Nothing needs root-cause analysis"
          emptyDescription="Every recent result passed — FAIL and INCONCLUSIVE results will show up here."
        />
      </div>
    </AppShell>
  );
}
