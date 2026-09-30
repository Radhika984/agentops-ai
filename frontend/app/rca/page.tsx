"use client";

import { useRouter } from "next/navigation";
import { AppShell } from "../components/AppShell";
import { PageHeader } from "../components/ui/PageHeader";
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
        <PageHeader
          title="RCA"
          description="Failed and inconclusive results across your account. Open one to see its real evidence, matched failure category, and explanation — or run a fresh analysis."
        />
        <ResultsTable
          verdicts={["FAIL", "INCONCLUSIVE"]}
          emptyTitle="Nothing needs root-cause analysis"
          emptyDescription="Every recent result passed — FAIL and INCONCLUSIVE results will show up here."
        />
      </div>
    </AppShell>
  );
}
