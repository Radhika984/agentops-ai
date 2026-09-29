"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../../../../components/AppShell";
import { Button } from "../../../../components/ui/Button";
import { Card } from "../../../../components/ui/Card";
import { Field } from "../../../../components/ui/Input";
import { ChevronLeftIcon } from "../../../../components/ui/icons";
import { ApiError, clearToken, createTestSuite } from "../../../../lib/api";
import { useRequireAuth } from "../../../../lib/useRequireAuth";

export default function CreateTestSuitePage() {
  const { agentId } = useParams<{ agentId: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();
  const checkedAuth = useRequireAuth();

  const [name, setName] = useState("");

  const createMutation = useMutation({
    mutationFn: () => createTestSuite(agentId, name),
    onSuccess: (suite) => {
      queryClient.invalidateQueries({ queryKey: ["test-suites", agentId] });
      router.push(`/agents/${agentId}/test-suites/${suite.id}`);
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || createMutation.isPending) return;
    createMutation.mutate();
  }

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href={`/agents/${agentId}`}
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        Agent
      </Link>
      <p className="text-sm font-semibold text-ink">New test suite</p>
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-2xl px-4 py-7 md:px-8">
        <h1 className="text-3xl font-bold tracking-tight text-ink">New test suite</h1>
        <p className="mt-1.5 text-sm text-ink-2">
          A test suite groups the test cases you&apos;ll run against this agent&apos;s versions.
        </p>

        <Card className="mt-6" elevation="raised">
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <Field
              label="Name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Core support flows"
              autoFocus
              required
            />

            <div className="flex items-center gap-2">
              <Button type="submit" variant="primary" disabled={createMutation.isPending || !name.trim()}>
                {createMutation.isPending ? "Creating…" : "Create test suite"}
              </Button>
              <Link href={`/agents/${agentId}`} className="no-underline">
                <Button type="button" variant="tertiary">
                  Cancel
                </Button>
              </Link>
            </div>

            {createMutation.isError && (
              <p className="text-xs text-danger">
                {createMutation.error instanceof ApiError
                  ? createMutation.error.message
                  : "Could not create this test suite."}
              </p>
            )}
          </form>
        </Card>
      </div>
    </AppShell>
  );
}
