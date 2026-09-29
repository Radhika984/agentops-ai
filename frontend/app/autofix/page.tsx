"use client";

import { useRouter } from "next/navigation";
import { ActivityList } from "../components/ActivityList";
import { AppShell } from "../components/AppShell";
import { ToolsIcon } from "../components/ui/icons";
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
        <h1 className="text-3xl font-bold tracking-tight text-ink">AutoFix</h1>
        <p className="mt-1.5 max-w-2xl text-sm text-ink-2">
          Every real AutoFix proposal across your account. Review, approve, or reject a pending
          proposal from the Approvals queue — this page is the real event history.
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
