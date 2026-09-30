"use client";

import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "../components/AppShell";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { PageHeader } from "../components/ui/PageHeader";
import { StatCard } from "../components/ui/StatCard";
import { CheckIcon, CostIcon, RunsIcon } from "../components/ui/icons";
import { ApiError, clearToken, getCostDashboard, type ModelGroupStats } from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

function formatCost(cost: number): string {
  return `$${cost.toFixed(6)}`;
}

function formatRate(rate: number | null): string {
  if (rate === null) return "—";
  return `${Math.round(rate * 100)}%`;
}

// A small, muted, warm-family palette reused from the existing design
// tokens (never a new hue) — enough distinct swatches to tell a handful
// of agents/models apart in a legend without reading as "rainbow".
const CHART_COLORS = [
  "var(--accent)",
  "var(--ink-2)",
  "var(--warning)",
  "var(--success)",
  "var(--danger)",
  "var(--ink-3)",
];

function groupByCallCount(stats: ModelGroupStats[], key: "agent" | "model"): Array<{ label: string; calls: number }> {
  const totals = new Map<string, number>();
  for (const s of stats) {
    totals.set(s[key], (totals.get(s[key]) ?? 0) + s.call_count);
  }
  return [...totals.entries()]
    .map(([label, calls]) => ({ label, calls }))
    .sort((a, b) => b.calls - a.calls);
}

/** Real-data donut: each agent's share of total calls, built with a plain
 * conic-gradient (no charting dependency) plus a text legend so the
 * breakdown is readable without relying on color alone. */
function UsageDonut({ stats }: { stats: ModelGroupStats[] }) {
  const groups = groupByCallCount(stats, "agent");
  const total = groups.reduce((sum, g) => sum + g.calls, 0);
  if (total === 0) return null;

  const cumulative = groups.reduce<number[]>((acc, g) => {
    const prev = acc.length > 0 ? acc[acc.length - 1] : 0;
    acc.push(prev + g.calls);
    return acc;
  }, []);
  const stops = groups.map((g, i) => {
    const start = ((cumulative[i] - g.calls) / total) * 360;
    const end = (cumulative[i] / total) * 360;
    return `${CHART_COLORS[i % CHART_COLORS.length]} ${start}deg ${end}deg`;
  });

  return (
    <Card elevation="raised">
      <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">Usage by agent</p>
      <div className="mt-4 flex items-center gap-5">
        <div
          className="h-28 w-28 shrink-0 rounded-full"
          style={{
            background: `conic-gradient(${stops.join(", ")})`,
            mask: "radial-gradient(farthest-side, transparent calc(100% - 16px), black calc(100% - 15px))",
            WebkitMask: "radial-gradient(farthest-side, transparent calc(100% - 16px), black calc(100% - 15px))",
          }}
          role="img"
          aria-label={`Call share by agent: ${groups.map((g) => `${g.label} ${Math.round((g.calls / total) * 100)}%`).join(", ")}`}
        />
        <ul className="flex min-w-0 flex-1 flex-col gap-1.5">
          {groups.map((g, i) => (
            <li key={g.label} className="flex items-center gap-2 text-xs">
              <span
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ background: CHART_COLORS[i % CHART_COLORS.length] }}
                aria-hidden="true"
              />
              <span className="min-w-0 flex-1 truncate text-ink-2">{g.label}</span>
              <span className="font-medium text-ink">{Math.round((g.calls / total) * 100)}%</span>
            </li>
          ))}
        </ul>
      </div>
    </Card>
  );
}

/** Real-data horizontal bars: each model's share of total calls. */
function UsageBars({ stats }: { stats: ModelGroupStats[] }) {
  const groups = groupByCallCount(stats, "model");
  const max = Math.max(...groups.map((g) => g.calls), 1);

  return (
    <Card elevation="raised">
      <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">Usage by model</p>
      <ul className="mt-4 flex flex-col gap-3">
        {groups.map((g, i) => (
          <li key={g.label}>
            <div className="flex items-center justify-between text-xs">
              <span className="truncate font-mono text-ink-2">{g.label}</span>
              <span className="font-medium text-ink">{g.calls}</span>
            </div>
            <div className="mt-1 h-1.5 w-full overflow-hidden rounded-full bg-surface-2">
              <div
                className="h-full rounded-full transition-all duration-300"
                style={{ width: `${(g.calls / max) * 100}%`, background: CHART_COLORS[i % CHART_COLORS.length] }}
              />
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function CostDashboardPage() {
  const router = useRouter();
  const checkedAuth = useRequireAuth();

  const costQuery = useQuery({
    queryKey: ["cost-dashboard"],
    queryFn: getCostDashboard,
    enabled: checkedAuth,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const report = costQuery.data;
  const totalCost = report?.stats.reduce((sum, s) => sum + s.total_cost, 0) ?? 0;
  const totalCalls = report?.stats.reduce((sum, s) => sum + s.call_count, 0) ?? 0;
  const totalCacheHits = report?.stats.reduce((sum, s) => sum + s.cache_hit_count, 0) ?? 0;
  const cacheHitRate = totalCalls > 0 ? `${Math.round((totalCacheHits / totalCalls) * 100)}%` : "—";

  return (
    <AppShell onLogout={handleLogout}>
      <div className="animate-fade-in-up mx-auto w-full max-w-5xl px-4 py-7 md:px-8">
        <PageHeader
          title="Cost"
          description={
            <>
              Spend per agent/model, from the model-call audit log. This project runs on the Gemini
              Free Tier — nothing here is billed. Figures are litellm&apos;s notional per-token
              estimate for the model actually used, useful for spotting relative cost/volume patterns.
            </>
          }
        />

        {costQuery.isError && (
          <p className="mt-6 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
            {costQuery.error instanceof ApiError
              ? costQuery.error.message
              : "Could not load the cost dashboard."}
          </p>
        )}

        <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <StatCard
            icon={<RunsIcon width={11} height={11} />}
            label="Total calls"
            value={costQuery.isLoading ? undefined : totalCalls}
            // A non-breaking space, not omitted: StatCard's label+value+
            // hint block is bottom-anchored inside a fixed-height card
            // (see StatCard.tsx), so a card with no hint line is shorter
            // and its label starts lower than the other two cards, which
            // both have a real hint line. This card has no real hint to
            // show, but still needs the same reserved line height so all
            // three cards' labels/values land at identical Y positions —
            // achieved here, from this page alone, without touching
            // StatCard's own layout logic.
            hint={" "}
            loading={costQuery.isLoading}
            isError={costQuery.isError}
            index={0}
            tone="orange"
          />
          <StatCard
            icon={<CheckIcon width={11} height={11} />}
            label="Cache hits"
            value={costQuery.isLoading ? undefined : totalCacheHits}
            hint={report && totalCalls > 0 ? `${cacheHitRate} of all calls` : undefined}
            loading={costQuery.isLoading}
            isError={costQuery.isError}
            index={1}
            tone="teal"
          />
          <StatCard
            icon={<CostIcon width={11} height={11} />}
            label="Estimated cost"
            value={costQuery.isLoading ? undefined : formatCost(totalCost)}
            hint={report ? "Free Tier — not billed" : undefined}
            loading={costQuery.isLoading}
            isError={costQuery.isError}
            index={2}
            tone="purple"
          />
        </div>

        {report && (
          <>
            {report.stats.length > 0 && (
              <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2">
                <UsageDonut stats={report.stats} />
                <UsageBars stats={report.stats} />
              </div>
            )}

            {report.recommendations.length > 0 && (
              <div className="mt-6">
                <p className="text-xs font-semibold uppercase tracking-wide text-ink-3">
                  Recommendations
                </p>
                <ul className="mt-2 flex flex-col gap-2">
                  {report.recommendations.map((rec, i) => (
                    <li
                      key={i}
                      className="rounded-lg border border-warning/30 bg-warning-soft px-3 py-2.5 text-sm text-ink"
                    >
                      <span className="font-medium text-warning">
                        {rec.agent} / {rec.model_group}
                      </span>
                      <span className="text-ink-2"> — {rec.message}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="mt-6">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-3">
                Recent usage
              </p>
              {report.stats.length === 0 ? (
                <EmptyState
                  icon={<CostIcon />}
                  title="No model calls yet"
                  description="Ask a question or run an agent to see usage here."
                />
              ) : (
                <Card elevation="raised" padded={false} className="overflow-x-auto">
                  <table className="w-full min-w-180 text-left text-sm">
                    <thead>
                      <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-3">
                        <th className="px-4 py-2.5 font-medium">Agent</th>
                        <th className="px-4 py-2.5 font-medium">Group</th>
                        <th className="px-4 py-2.5 font-medium">Model</th>
                        <th className="px-4 py-2.5 text-right font-medium">Calls</th>
                        <th className="px-4 py-2.5 text-right font-medium">Cache hits</th>
                        <th className="px-4 py-2.5 text-right font-medium">Cost</th>
                        <th className="px-4 py-2.5 text-right font-medium">Avg tokens in/out</th>
                        <th className="px-4 py-2.5 text-right font-medium">Run success</th>
                      </tr>
                    </thead>
                    <tbody>
                      {report.stats.map((s, i) => (
                        <tr
                          key={i}
                          className="border-b border-line text-ink-2 tabular-nums transition-colors duration-150 last:border-b-0 hover:bg-surface-2"
                        >
                          <td className="px-4 py-2.5 font-medium text-ink">{s.agent}</td>
                          <td className="px-4 py-2.5">{s.model_group}</td>
                          <td className="px-4 py-2.5">{s.model}</td>
                          <td className="px-4 py-2.5 text-right">{s.call_count}</td>
                          <td className="px-4 py-2.5 text-right">{s.cache_hit_count}</td>
                          <td className="px-4 py-2.5 text-right">{formatCost(s.total_cost)}</td>
                          <td className="px-4 py-2.5 text-right">
                            {Math.round(s.avg_tokens_in)} / {Math.round(s.avg_tokens_out)}
                          </td>
                          <td className="px-4 py-2.5 text-right">{formatRate(s.run_success_rate)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              )}
            </div>
          </>
        )}
      </div>
    </AppShell>
  );
}
