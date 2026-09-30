"use client";

import { useRouter } from "next/navigation";
import { ActivityList } from "../components/ActivityList";
import { AppShell } from "../components/AppShell";
import { ToolsIcon } from "../components/ui/icons";
import { PageHeader } from "../components/ui/PageHeader";
import { clearToken } from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

export default function AutoFixPage() {
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
          title="AutoFix"
          description="Every real AutoFix proposal across your account — this page is the real event history."
        />
        <p className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-ink-3">
          <span className="font-medium text-ink-2">AI proposes, humans decide:</span>
          Propose
          <span className="text-ink-3">→</span>
          Review in the Approvals queue
          <span className="text-ink-3">→</span>
          Re-verify. A proposal never silently modifies an agent version&apos;s configuration.
        </p>
        <ActivityList
          eventType="autofix_proposed"
          emptyIcon={<ToolsIcon />}
          emptyTitle="No AutoFix proposals yet"
          emptyDescription="Propose a fix for a failing or inconclusive result to see it recorded here."
        />
      </div>
    </AppShell>
  );
}
