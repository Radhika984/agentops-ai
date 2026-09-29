"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../../../../components/AppShell";
import { Badge, type Tone } from "../../../../components/ui/Badge";
import { Button } from "../../../../components/ui/Button";
import { Card } from "../../../../components/ui/Card";
import { Disclosure, LabeledCodeBlock } from "../../../../components/ui/CodeDisclosure";
import { EmptyState } from "../../../../components/ui/EmptyState";
import { Skeleton } from "../../../../components/ui/Skeleton";
import { ChevronLeftIcon, VerifyIcon } from "../../../../components/ui/icons";
import {
  ApiError,
  acceptCandidateTestCase,
  clearToken,
  deleteTestCase,
  getTestSuite,
  listTestCases,
  type TestCaseRead,
} from "../../../../lib/api";
import { useRequireAuth } from "../../../../lib/useRequireAuth";

/** Real, factual chips summarizing which of the five ground-truth
 * mechanisms (backend/app/services/test_suite_service.py's
 * GROUND_TRUTH_FIELDS) this case actually has set — never a fabricated
 * "coverage score". */
function groundTruthBadges(tc: TestCaseRead): string[] {
  const badges: string[] = [];
  if (tc.expected_output) badges.push("expected output");
  if (tc.assertions && tc.assertions.length > 0) {
    badges.push(`${tc.assertions.length} assertion${tc.assertions.length === 1 ? "" : "s"}`);
  }
  if (tc.reference_context) badges.push("reference context");
  if (tc.expected_tool_calls && tc.expected_tool_calls.length > 0) {
    badges.push(`${tc.expected_tool_calls.length} tool call${tc.expected_tool_calls.length === 1 ? "" : "s"}`);
  }
  if (tc.rubric) badges.push("rubric");
  return badges;
}

function statusTone(status: TestCaseRead["status"]): Tone {
  return status === "candidate" ? "warning" : "success";
}

function TestCaseCard({
  agentId,
  suiteId,
  testCase,
}: {
  agentId: string;
  suiteId: string;
  testCase: TestCaseRead;
}) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const queryClient = useQueryClient();

  const deleteMutation = useMutation({
    mutationFn: () => deleteTestCase(testCase.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["test-cases", suiteId] });
    },
  });

  const acceptMutation = useMutation({
    mutationFn: () => acceptCandidateTestCase(testCase.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["test-cases", suiteId] });
    },
  });

  const badges = groundTruthBadges(testCase);

  return (
    <Card elevation="raised">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="truncate text-sm font-semibold text-ink">{testCase.name}</p>
            <Badge tone={statusTone(testCase.status)}>{testCase.status}</Badge>
          </div>
          {(badges.length > 0 || testCase.tags.length > 0) && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {badges.map((b) => (
                <Badge key={b} tone="neutral">
                  {b}
                </Badge>
              ))}
              {testCase.tags.map((t) => (
                <Badge key={t} tone="accent">
                  {t}
                </Badge>
              ))}
            </div>
          )}
          <p className="mt-1.5 text-xs text-ink-3">
            Trial count {testCase.trial_count}
            {testCase.latency_threshold_ms !== null && ` · Latency ≤ ${testCase.latency_threshold_ms}ms`}
            {" · Updated "}
            {new Date(testCase.updated_at).toLocaleDateString()}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          {testCase.status === "candidate" && (
            <Button
              variant="secondary"
              size="sm"
              onClick={() => acceptMutation.mutate()}
              disabled={acceptMutation.isPending}
            >
              {acceptMutation.isPending ? "Accepting…" : "Accept candidate"}
            </Button>
          )}
          <Link
            href={`/agents/${agentId}/test-suites/${suiteId}/test-cases/${testCase.id}/edit`}
            className="no-underline"
          >
            <Button variant="secondary" size="sm">
              Edit
            </Button>
          </Link>
          {!confirmingDelete && (
            <Button variant="danger" size="sm" onClick={() => setConfirmingDelete(true)}>
              Delete
            </Button>
          )}
        </div>
      </div>

      {confirmingDelete && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <span className="text-xs text-ink-2">
            Delete &ldquo;{testCase.name}&rdquo;? This can&apos;t be undone.
          </span>
          <Button
            variant="danger"
            size="sm"
            onClick={() => deleteMutation.mutate()}
            disabled={deleteMutation.isPending}
          >
            {deleteMutation.isPending ? "Deleting…" : "Confirm delete"}
          </Button>
          <Button
            variant="tertiary"
            size="sm"
            onClick={() => setConfirmingDelete(false)}
            disabled={deleteMutation.isPending}
          >
            Cancel
          </Button>
        </div>
      )}

      {(deleteMutation.isError || acceptMutation.isError) && (
        <p className="mt-2 text-xs text-danger">
          {deleteMutation.error instanceof ApiError
            ? deleteMutation.error.message
            : acceptMutation.error instanceof ApiError
              ? acceptMutation.error.message
              : "Could not complete this action."}
        </p>
      )}

      <div className="mt-3 border-t border-line pt-3">
        <Disclosure summary="View details">
          <div className="flex flex-col gap-2.5 text-xs">
          <LabeledCodeBlock label="Input" value={testCase.input} />

          {testCase.expected_output && (
            <div>
              <p className="font-semibold tracking-wide text-ink-3 uppercase">Expected output</p>
              <p className="mt-1 whitespace-pre-wrap text-ink-2">{testCase.expected_output}</p>
            </div>
          )}

          {testCase.assertions && testCase.assertions.length > 0 && (
            <div>
              <p className="font-semibold tracking-wide text-ink-3 uppercase">Assertions</p>
              <ul className="mt-1 flex flex-col gap-1">
                {testCase.assertions.map((a, i) => (
                  <li key={i} className="font-mono text-[11px] text-ink-2">
                    {a.path} {a.op}
                    {a.op !== "exists" && a.value !== undefined && a.value !== null
                      ? ` ${JSON.stringify(a.value)}`
                      : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {testCase.expected_tool_calls && testCase.expected_tool_calls.length > 0 && (
            <div>
              <p className="font-semibold tracking-wide text-ink-3 uppercase">Expected tool calls</p>
              <ul className="mt-1 flex flex-col gap-1">
                {testCase.expected_tool_calls.map((c, i) => (
                  <li key={i} className="font-mono text-[11px] text-ink-2">
                    {c.order_index !== null && c.order_index !== undefined ? `${c.order_index}. ` : ""}
                    {c.tool}
                    {c.required === false ? " (optional)" : ""}
                    {c.args_constraints && c.args_constraints.length > 0
                      ? ` — ${c.args_constraints.length} arg constraint${c.args_constraints.length === 1 ? "" : "s"}`
                      : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {testCase.reference_context && (
            <div>
              <p className="font-semibold tracking-wide text-ink-3 uppercase">Reference context</p>
              <p className="mt-1 whitespace-pre-wrap text-ink-2">{testCase.reference_context}</p>
            </div>
          )}

          {testCase.rubric && (
            <div>
              <p className="font-semibold tracking-wide text-ink-3 uppercase">Rubric</p>
              <p className="mt-1 whitespace-pre-wrap text-ink-2">
                {testCase.rubric} (threshold {testCase.rubric_threshold})
              </p>
            </div>
          )}

          {testCase.output_schema && (
            <LabeledCodeBlock label="Output schema" value={testCase.output_schema} />
          )}
          </div>
        </Disclosure>
      </div>
    </Card>
  );
}

export default function TestSuiteDetailPage() {
  const { agentId, suiteId } = useParams<{ agentId: string; suiteId: string }>();
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  const suiteQuery = useQuery({
    queryKey: ["test-suite", agentId, suiteId],
    queryFn: () => getTestSuite(agentId, suiteId),
    enabled: checkedAuth,
  });

  const casesQuery = useQuery({
    queryKey: ["test-cases", suiteId],
    queryFn: () => listTestCases(suiteId),
    enabled: checkedAuth,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const suite = suiteQuery.data;
  const cases = casesQuery.data ?? [];

  const breadcrumb = (
    <div className="min-w-0">
      <Link
        href={`/agents/${agentId}`}
        className="inline-flex items-center gap-1 text-xs font-medium text-ink-3 no-underline hover:text-ink"
      >
        <ChevronLeftIcon />
        Agent
      </Link>
      {suite && <p className="truncate text-sm font-semibold text-ink">{suite.name}</p>}
    </div>
  );

  return (
    <AppShell onLogout={handleLogout} breadcrumb={breadcrumb}>
      <div className="animate-fade-in-up mx-auto w-full max-w-3xl px-4 py-7 md:px-8">
        {suiteQuery.isLoading && (
          <div className="flex flex-col gap-3">
            <Skeleton className="h-8 w-64" />
            <Skeleton className="h-20" />
          </div>
        )}

        {suiteQuery.isError && (
          <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {suiteQuery.error instanceof ApiError ? suiteQuery.error.message : "Could not load this test suite."}
          </p>
        )}

        {suite && (
          <>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h1 className="text-3xl font-bold tracking-tight text-ink">{suite.name}</h1>
                <p className="mt-1.5 text-sm text-ink-2">
                  {cases.length} test case{cases.length === 1 ? "" : "s"} · Created{" "}
                  {new Date(suite.created_at).toLocaleDateString()} · Updated{" "}
                  {new Date(suite.updated_at).toLocaleDateString()}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <Link href={`/agents/${agentId}/test-suites/${suiteId}/run`} className="no-underline">
                  <Button variant="secondary">Run suite</Button>
                </Link>
                <Link
                  href={`/agents/${agentId}/test-suites/${suiteId}/test-cases/new`}
                  className="no-underline"
                >
                  <Button variant="primary">+ New test case</Button>
                </Link>
              </div>
            </div>

            <div className="mt-6 flex flex-col gap-3">
              {casesQuery.isLoading && (
                <>
                  <Skeleton className="h-24" />
                  <Skeleton className="h-24" />
                </>
              )}

              {casesQuery.isError && (
                <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                  {casesQuery.error instanceof ApiError
                    ? casesQuery.error.message
                    : "Could not load test cases."}
                </p>
              )}

              {casesQuery.data && cases.length === 0 && (
                <EmptyState
                  icon={<VerifyIcon />}
                  title="No test cases yet"
                  description="Add a test case with at least one ground-truth mechanism to start evaluating this suite."
                  action={
                    <Link
                      href={`/agents/${agentId}/test-suites/${suiteId}/test-cases/new`}
                      className="no-underline"
                    >
                      <Button variant="primary">+ Create the first test case</Button>
                    </Link>
                  }
                />
              )}

              {cases.map((tc) => (
                <TestCaseCard key={tc.id} agentId={agentId} suiteId={suiteId} testCase={tc} />
              ))}
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
