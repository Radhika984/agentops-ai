"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Badge, type Tone } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Card } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";
import { Skeleton } from "./ui/Skeleton";
import { RCAIcon } from "./ui/icons";
import { ApiError, listAllResults, type Verdict } from "../lib/api";

const PAGE_SIZE = 20;

const VERDICT_TONE: Record<string, Tone> = { PASS: "success", FAIL: "danger", INCONCLUSIVE: "warning" };

/** Shared table for the account-wide "Evaluation" (all verdicts) and
 * "RCA" (verdicts=[FAIL, INCONCLUSIVE]) nav pages — same real backend
 * capability (GET /api/v1/results), just a different filter, so this is
 * one component configured by props rather than two near-duplicate
 * pages. Every row navigates to the real result detail page, where RCA
 * is actually run. */
export function ResultsTable({
  verdicts,
  emptyTitle,
  emptyDescription,
}: {
  verdicts?: Verdict[];
  emptyTitle: string;
  emptyDescription: string;
}) {
  const router = useRouter();
  const [offset, setOffset] = useState(0);

  const resultsQuery = useQuery({
    queryKey: ["results", verdicts?.join(",") ?? "all", offset],
    queryFn: () => listAllResults({ verdicts, limit: PAGE_SIZE, offset }),
  });

  const total = resultsQuery.data?.total ?? 0;
  const hasNext = offset + PAGE_SIZE < total;
  const hasPrev = offset > 0;

  return (
    <>
      <Card elevation="raised" padded={false} className="mt-7 overflow-hidden">
        {resultsQuery.isLoading && (
          <div className="flex flex-col gap-2 p-5">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        )}

        {resultsQuery.isError && (
          <p className="m-5 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {resultsQuery.error instanceof ApiError
              ? resultsQuery.error.message
              : "Could not load results."}
          </p>
        )}

        {resultsQuery.data && resultsQuery.data.items.length === 0 && (
          <div className="p-5">
            <EmptyState icon={<RCAIcon />} title={emptyTitle} description={emptyDescription} />
          </div>
        )}

        {resultsQuery.data && resultsQuery.data.items.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-3">
                  <th className="px-5 py-2.5 font-medium">Test case</th>
                  <th className="px-3 py-2.5 font-medium">Agent</th>
                  <th className="px-3 py-2.5 font-medium">Suite</th>
                  <th className="px-3 py-2.5 font-medium">Verdict</th>
                  <th className="px-3 py-2.5 font-medium">Latency</th>
                  <th className="px-5 py-2.5 text-right font-medium">Recorded</th>
                </tr>
              </thead>
              <tbody>
                {resultsQuery.data.items.map((result) => (
                  <tr
                    key={result.id}
                    className="cursor-pointer border-b border-line transition-colors duration-150 last:border-b-0 hover:bg-surface-2"
                    onClick={() =>
                      router.push(
                        `/agents/${result.agent_id}/test-suites/${result.suite_id}/runs/${result.suite_run_id}/results/${result.id}`,
                      )
                    }
                  >
                    <td className="max-w-[180px] truncate px-5 py-2.5 text-ink">
                      {result.test_case_name}
                    </td>
                    <td className="max-w-[140px] truncate px-3 py-2.5 text-ink-2">
                      {result.agent_name}
                    </td>
                    <td className="max-w-[140px] truncate px-3 py-2.5 text-ink-2">
                      {result.suite_name}
                    </td>
                    <td className="px-3 py-2.5">
                      <Badge tone={VERDICT_TONE[result.verdict] ?? "neutral"}>
                        {result.verdict}
                      </Badge>
                    </td>
                    <td className="px-3 py-2.5 text-ink-2 tabular-nums">
                      {result.latency_ms !== null ? `${result.latency_ms}ms` : "—"}
                    </td>
                    <td className="px-5 py-2.5 text-right text-xs text-ink-3">
                      {new Date(result.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {total > PAGE_SIZE && (
        <div className="mt-4 flex items-center justify-between text-sm text-ink-3">
          <span>
            {offset + 1}–{Math.min(offset + PAGE_SIZE, total)} of {total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={!hasPrev}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={!hasNext}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </>
  );
}
