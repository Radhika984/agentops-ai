"use client";

import { useRouter } from "next/navigation";
import { ActivityList } from "../components/ActivityList";
import { AppShell } from "../components/AppShell";
import { ReleaseIcon } from "../components/ui/icons";
import { Badge } from "../components/ui/Badge";
import { PageHeader } from "../components/ui/PageHeader";
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
        <PageHeader
          title="Release Gate"
          description="Every real Release Gate evaluation across your account, computed from persisted SuiteRun evidence. Open a suite run to re-evaluate or review it in full."
        />
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-ink-3">
          <span className="flex items-center gap-1.5">
            <Badge tone="danger">hard gate</Badge>
            deterministic — blocks release
          </span>
          <span className="flex items-center gap-1.5">
            <Badge tone="neutral">soft signal</Badge>
            score-based — informs the decision only
          </span>
        </div>
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
