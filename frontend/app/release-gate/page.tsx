"use client";

import { useRouter } from "next/navigation";
import { ActivityList } from "../components/ActivityList";
import { AppShell } from "../components/AppShell";
import { ReleaseIcon } from "../components/ui/icons";
import { clearToken } from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

export default function ReleaseGatePage() {
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  return (
    <AppShell onLogout={handleLogout}>
      <div className="animate-fade-in-up mx-auto w-full max-w-4xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">Release Gate</h1>
        <p className="mt-1.5 max-w-2xl text-sm text-ink-2">
          Every real Release Gate evaluation across your account — deterministic hard-gate/soft
          -score decisions, computed from persisted SuiteRun evidence. Open a suite run to
          re-evaluate or review it in full.
        </p>
        <ActivityList
          eventType="release_gate_evaluated"
          emptyIcon={<ReleaseIcon />}
          emptyTitle="No release gate evaluations yet"
          emptyDescription="Evaluate a completed suite run's release gate to see the decision recorded here."
        />
      </div>
    </AppShell>
  );
}
