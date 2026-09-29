"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "../components/AppShell";
import { Badge, type Tone } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { StatCard, STAT_TONE_CLASSES, type StatTone } from "../components/ui/StatCard";
import {
  AgentIcon,
  ApprovalsIcon,
  ArrowRightIcon,
  BrandMark,
  ClockIcon,
  InboxIcon,
  MoonIcon,
  ProjectsIcon,
  ReleaseIcon,
  RunsIcon,
  SunIcon,
  SunriseIcon,
  SunsetIcon,
  TestSuitesIcon,
  ToolsIcon,
} from "../components/ui/icons";
import {
  clearToken,
  getCurrentUser,
  getDashboardStats,
  getPerformanceOverview,
  getRecentSuiteRuns,
  getVerdictDistribution,
  listActivity,
  type ActivityEventRead,
  type SuiteRunSummary,
} from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

type TimeOfDay = { label: string; icon: ReactNode };

function timeOfDayForHour(hour: number): TimeOfDay {
  if (hour < 5) return { label: "Good night", icon: <MoonIcon /> };
  if (hour < 12) return { label: "Good morning", icon: <SunriseIcon /> };
  if (hour < 17) return { label: "Good afternoon", icon: <SunIcon /> };
  if (hour < 21) return { label: "Good evening", icon: <SunsetIcon /> };
  return { label: "Good night", icon: <MoonIcon /> };
}

// Same technique as useRequireAuth.ts's useSyncExternalStore usage, and
// for the same reason: the viewer's local hour is only knowable in the
// browser, so computing it during a normal render would run once on the
// server (in whatever timezone the container happens to be in) and again
// on the client — a genuine text mismatch, the same hydration-bug class
// already fixed once in useRequireAuth. getServerTimeOfDaySnapshot
// returning `null` for both the server render and the client's first
// (hydration) render keeps that first render identical on both sides;
// the real greeting only appears in React's corrective re-render right
// after hydrating.
//
// Module-scoped caching (not a useState+useEffect pair) is deliberate:
// useSyncExternalStore's getSnapshot must return a referentially stable
// value when nothing has actually changed, or React treats every render
// as "the store changed" and re-renders synchronously forever. Caching
// by hour means the reference only changes when the hour bucket itself
// does — which also means, as a side effect, the greeting corrects
// itself if the dashboard is left open across an hour boundary, without
// a polling interval.
let cachedHour = -1;
let cachedTimeOfDay: TimeOfDay = timeOfDayForHour(0);

function getTimeOfDaySnapshot(): TimeOfDay {
  const hour = new Date().getHours();
  if (hour !== cachedHour) {
    cachedHour = hour;
    cachedTimeOfDay = timeOfDayForHour(hour);
  }
  return cachedTimeOfDay;
}

function getServerTimeOfDaySnapshot(): TimeOfDay | null {
  return null;
}

function subscribeNever(): () => void {
  return () => {};
}

function useTimeOfDay(): TimeOfDay | null {
  return useSyncExternalStore(subscribeNever, getTimeOfDaySnapshot, getServerTimeOfDaySnapshot);
}

function relativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

const VERDICT_TONE: Record<string, Tone> = { PASS: "success", FAIL: "danger", INCONCLUSIVE: "warning" };
const STATUS_TONE: Record<string, Tone> = {
  completed: "success",
  failed: "danger",
  running: "accent",
  pending: "neutral",
  cancelling: "warning",
};

const ACTIVITY_ICON: Record<string, ReactNode> = {
  suite_run_completed: <RunsIcon />,
  release_gate_evaluated: <ReleaseIcon />,
  autofix_proposed: <ToolsIcon />,
  approval_decided: <ApprovalsIcon />,
  agent_version_created: <AgentIcon />,
  agent_version_promoted: <AgentIcon />,
};

/** Real, data-driven color-coding for each activity row's icon chip —
 * never a fixed color per event_type alone where the event's own
 * already-stored metadata (see app/services/activity_service.py's
 * record() calls) says something more specific: a held release or a
 * rejected approval reads pink/danger, a passed release or an approved
 * decision reads teal, a suite run's color reflects whether it actually
 * had a failure. AutoFix (always "something needs review") and version
 * events (no pass/fail meaning) get one fixed categorical tone each. */
function activityTone(event: ActivityEventRead): StatTone {
  const meta = event.event_metadata;
  switch (event.event_type) {
    case "suite_run_completed": {
      const failCount = Number(meta.fail_count ?? 0);
      const inconclusiveCount = Number(meta.inconclusive_count ?? 0);
      if (failCount > 0) return "pink";
      if (inconclusiveCount > 0) return "orange";
      return "teal";
    }
    case "release_gate_evaluated":
      return meta.decision === "hold" ? "pink" : "teal";
    case "approval_decided":
      return meta.approved === true ? "teal" : "pink";
    case "autofix_proposed":
      return "orange";
    case "agent_version_created":
    case "agent_version_promoted":
      return "purple";
    default:
      return "orange";
  }
}

function QuickAction({
  icon,
  label,
  href,
  primary,
}: {
  icon: ReactNode;
  label: string;
  href: string;
  primary?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`flex items-center justify-between gap-3 rounded-lg border px-3.5 py-3 text-sm font-medium no-underline transition-all duration-150 ${
        primary
          ? "border-transparent bg-accent text-accent-ink shadow-sm hover:bg-accent-hover"
          : "border-line-strong bg-linear-to-r from-surface-elevated to-surface text-ink backdrop-blur-md hover:border-line-strong hover:to-surface-2"
      }`}
    >
      <span className="flex items-center gap-2.5">
        {icon}
        {label}
      </span>
      <ArrowRightIcon className="shrink-0 opacity-60" />
    </Link>
  );
}

function verdictLabel(run: SuiteRunSummary): ReactNode {
  if (run.status !== "completed" && run.status !== "failed") {
    return <Badge tone={STATUS_TONE[run.status] ?? "neutral"}>{run.status}</Badge>;
  }
  if (!run.verdict) return <span className="text-ink-3">—</span>;
  return <Badge tone={VERDICT_TONE[run.verdict] ?? "neutral"}>{run.verdict}</Badge>;
}

/** A hand-rolled SVG donut — no new charting dependency. Segments are
 * simple stroke-dasharray arcs; skipped entirely (a real empty state,
 * not a gray fake ring) when there is no evaluation data yet. */
function VerdictDonut({
  pass,
  fail,
  inconclusive,
}: {
  pass: number;
  fail: number;
  inconclusive: number;
}) {
  const total = pass + fail + inconclusive;
  if (total === 0) {
    return (
      <EmptyState
        icon={<InboxIcon />}
        title="No evaluation results yet"
        description="Run a test suite to see verdicts here."
      />
    );
  }
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const segments: { value: number; color: string }[] = [
    { value: pass, color: "var(--success)" },
    { value: fail, color: "var(--danger)" },
    { value: inconclusive, color: "var(--warning)" },
  ];
  let offset = 0;
  return (
    <div className="flex items-center gap-6">
      <svg width="112" height="112" viewBox="0 0 112 112" className="shrink-0 -rotate-90">
        <circle cx="56" cy="56" r={radius} fill="none" stroke="var(--surface-2)" strokeWidth="12" />
        {segments.map((seg, i) => {
          if (seg.value === 0) return null;
          const length = (seg.value / total) * circumference;
          const dasharray = `${length} ${circumference - length}`;
          const el = (
            <circle
              key={i}
              cx="56"
              cy="56"
              r={radius}
              fill="none"
              stroke={seg.color}
              strokeWidth="12"
              strokeDasharray={dasharray}
              strokeDashoffset={-offset}
              strokeLinecap="butt"
            />
          );
          offset += length;
          return el;
        })}
        <text
          x="56"
          y="56"
          textAnchor="middle"
          dominantBaseline="central"
          transform="rotate(90 56 56)"
          className="fill-ink text-xl font-bold"
        >
          {total}
        </text>
      </svg>
      <div className="flex flex-col gap-2 text-sm">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-success" />
          <span className="text-ink-2">PASS</span>
          <span className="font-semibold text-ink tabular-nums">{pass}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-danger" />
          <span className="text-ink-2">FAIL</span>
          <span className="font-semibold text-ink tabular-nums">{fail}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full bg-warning" />
          <span className="text-ink-2">INCONCLUSIVE</span>
          <span className="font-semibold text-ink tabular-nums">{inconclusive}</span>
        </div>
      </div>
    </div>
  );
}

export default function HomePage() {
  const router = useRouter();
  const checkedAuth = useRequireAuth();
  const timeOfDay = useTimeOfDay();

  const userQuery = useQuery({
    queryKey: ["me"],
    queryFn: getCurrentUser,
    enabled: checkedAuth,
    staleTime: 5 * 60 * 1000,
  });

  const statsQuery = useQuery({
    queryKey: ["dashboard", "stats"],
    queryFn: getDashboardStats,
    enabled: checkedAuth,
  });

  const recentRunsQuery = useQuery({
    queryKey: ["dashboard", "recent-suite-runs"],
    queryFn: () => getRecentSuiteRuns(6, 0),
    enabled: checkedAuth,
  });

  const activityQuery = useQuery({
    queryKey: ["activity", "recent"],
    queryFn: () => listActivity(6),
    enabled: checkedAuth,
  });

  const verdictQuery = useQuery({
    queryKey: ["dashboard", "verdict-distribution"],
    queryFn: getVerdictDistribution,
    enabled: checkedAuth,
  });

  const performanceQuery = useQuery({
    queryKey: ["dashboard", "performance"],
    queryFn: () => getPerformanceOverview(7),
    enabled: checkedAuth,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const displayName = userQuery.data?.full_name || userQuery.data?.email;

  return (
    <AppShell onLogout={handleLogout}>
      <div className="mx-auto w-full max-w-6xl px-4 py-7 md:px-8">
        {/* ---- Hero -------------------------------------------------- */}
        {/* No Card wrapper here, deliberately: Card always renders its
            own border + surface background, which is exactly what made
            this read as a distinct rectangular panel sitting on the
            page rather than part of the page itself. A plain div has no
            border and no background of its own, so the dashboard's own
            --background (set by .app-canvas) shows straight through —
            the hero's atmosphere comes entirely from the decorative
            layers below, not from a surface color underneath them. */}
        <div className="animate-fade-in-up bg-technical-grid-dark relative overflow-hidden rounded-2xl px-5 py-6 md:px-7 md:py-7">
          {/* Left-to-right atmosphere: warm brown wash near the text,
              gradually giving way to a navy-black tint toward the right
              edge — the same brown-to-navy blend the sidebar-to-dashboard
              transition uses, echoed inside the hero itself. Two layered
              gradients (not one), so the shift reads as gradual rather
              than a hard split. */}
          <div
            className="pointer-events-none absolute inset-0 bg-linear-to-br from-accent/6 via-transparent to-transparent"
            aria-hidden="true"
          />
          <div
            className="pointer-events-none absolute inset-y-0 right-0 w-2/3 bg-linear-to-l from-surface-elevated/40 via-surface-elevated/8 to-transparent"
            aria-hidden="true"
          />
          {/* Large soft atmospheric spheres behind the orbit — the
              reference's own "large translucent circular object" scale,
              not just the small orbit ring below. Deliberately reined in
              from earlier passes: lower peak color-mix percentage and
              opacity so this reads as one restrained, elegant amber
              sphere blended into the navy canvas, not a giant glowing
              brown blob sitting behind the whole planet system. Purely
              decorative, clipped by this section's own overflow-hidden. */}
          <div
            className="pointer-events-none absolute top-1/2 right-[4%] h-72 w-72 -translate-y-1/2 rounded-full opacity-50 blur-xl"
            style={{
              background:
                "radial-gradient(circle at 35% 35%, color-mix(in srgb, var(--accent) 65%, transparent) 0%, color-mix(in srgb, var(--accent) 35%, transparent) 45%, transparent 72%)",
            }}
            aria-hidden="true"
          />
          <div
            className="pointer-events-none absolute top-[16%] right-0 h-40 w-40 rounded-full opacity-45 blur-lg"
            style={{
              background:
                "radial-gradient(circle at 40% 40%, color-mix(in srgb, #f5efe6 45%, var(--surface-elevated) 55%) 0%, color-mix(in srgb, #f5efe6 18%, transparent) 45%, transparent 72%)",
            }}
            aria-hidden="true"
          />
          <div className="relative flex flex-wrap items-center justify-between gap-6">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-1.5 text-xs font-medium text-ink-3">
                {userQuery.isLoading || !timeOfDay ? (
                  <Skeleton className="h-3.5 w-40" />
                ) : (
                  displayName && (
                    <>
                      <span className="text-accent">{timeOfDay.icon}</span>
                      {timeOfDay.label}, {displayName}
                    </>
                  )
                )}
              </div>
              <h1 className="mt-1 text-2xl font-bold tracking-tight text-ink md:text-3xl">
                Build safer, more reliable <span className="text-accent">AI agents</span>
              </h1>
              <p className="mt-2 max-w-lg text-sm text-ink-2">
                AgentOps helps you evaluate, monitor and release AI agents with confidence.
              </p>
            </div>
            <div
              className="relative hidden h-40 w-40 shrink-0 items-center justify-center lg:flex"
              aria-hidden="true"
            >
              {/* Thin elliptical orbital rings — a second, wider ring at
                  an angle behind the original circular one, reading as a
                  true "orbit" rather than one flat circle. */}
              <span
                className="absolute h-44 w-28 rounded-full border border-accent/30"
                style={{ transform: "rotate(-18deg)" }}
              />
              <span
                className="absolute h-32 w-44 rounded-full border border-accent/20"
                style={{ transform: "rotate(12deg)" }}
              />
              <span className="animate-orbit-spin absolute inset-2 rounded-full border border-dashed border-accent/40" />
              <span className="absolute inset-8 rounded-full border border-line-strong" />
              <span className="relative flex h-14 w-14 items-center justify-center rounded-full bg-surface-elevated text-accent shadow-lg ring-1 ring-accent/20">
                <BrandMark width={26} height={26} />
              </span>
              <span
                className="animate-float-slow absolute top-1 right-3 h-2.5 w-2.5 rounded-full bg-accent shadow-[0_0_10px_var(--accent)]"
                style={{ animationDelay: "-1.5s" }}
              />
              <span
                className="animate-float-slow absolute bottom-3 left-0 h-2 w-2 rounded-full bg-stat-teal shadow-[0_0_8px_var(--stat-teal)]"
                style={{ animationDelay: "-4s" }}
              />
            </div>
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_300px]">
          <div className="flex flex-col gap-6">
            {/* ---- Stat tiles ------------------------------------------ */}
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <StatCard
                icon={<ProjectsIcon width={11} height={11} />}
                label="Total projects"
                value={statsQuery.data?.total_projects}
                loading={statsQuery.isLoading}
                isError={statsQuery.isError}
                index={0}
                tone="orange"
                href="/projects"
              />
              <StatCard
                icon={<AgentIcon width={11} height={11} />}
                label="Agents"
                value={statsQuery.data?.total_agents}
                loading={statsQuery.isLoading}
                isError={statsQuery.isError}
                index={1}
                tone="teal"
                href="/agents"
              />
              <StatCard
                icon={<RunsIcon width={11} height={11} />}
                label="Total suite runs"
                value={statsQuery.data?.total_suite_runs}
                loading={statsQuery.isLoading}
                isError={statsQuery.isError}
                index={2}
                tone="purple"
                href="/runs"
              />
              <StatCard
                icon={<ReleaseIcon width={11} height={11} />}
                label="Release gate holds"
                value={statsQuery.data?.release_gate_holds}
                loading={statsQuery.isLoading}
                isError={statsQuery.isError}
                index={3}
                tone="pink"
                href="/release-gate"
              />
            </div>

            {/* ---- Recent Suite Runs ------------------------------------ */}
            <Card elevation="raised" padded={false} className="overflow-hidden">
              <div className="flex items-center justify-between border-b border-line px-5 py-4">
                <h2 className="text-sm font-semibold text-ink">Recent Suite Runs</h2>
                <Link href="/runs" className="flex items-center gap-1 text-xs font-medium text-accent no-underline hover:text-accent-hover">
                  View all <ArrowRightIcon />
                </Link>
              </div>
              {recentRunsQuery.isLoading && (
                <div className="flex flex-col gap-2 p-5">
                  <Skeleton className="h-10" />
                  <Skeleton className="h-10" />
                  <Skeleton className="h-10" />
                </div>
              )}
              {recentRunsQuery.data && recentRunsQuery.data.items.length === 0 && (
                <div className="p-5">
                  <EmptyState
                    icon={<RunsIcon />}
                    title="No suite runs yet"
                    description="Run a test suite against an agent version to see it here."
                    action={
                      <Link href="/test-suites" className="no-underline">
                        <Button variant="primary">Go to test suites</Button>
                      </Link>
                    }
                  />
                </div>
              )}
              {recentRunsQuery.data && recentRunsQuery.data.items.length > 0 && (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] text-left text-sm">
                    <thead>
                      <tr className="border-b border-line text-xs uppercase tracking-wide text-ink-3">
                        <th className="px-5 py-2.5 font-medium">Project</th>
                        <th className="px-3 py-2.5 font-medium">Agent</th>
                        <th className="px-3 py-2.5 font-medium">Version</th>
                        <th className="px-3 py-2.5 font-medium">Status</th>
                        <th className="px-3 py-2.5 font-medium">Verdict</th>
                        <th className="px-5 py-2.5 text-right font-medium">Completed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {recentRunsQuery.data.items.map((run) => (
                        <tr
                          key={run.id}
                          className="cursor-pointer border-b border-line transition-colors duration-150 last:border-b-0 hover:bg-surface-2"
                          onClick={() =>
                            router.push(
                              `/agents/${run.agent_id}/test-suites/${run.suite_id}/runs/${run.id}`,
                            )
                          }
                        >
                          <td className="max-w-[140px] truncate px-5 py-2.5 text-ink">
                            {run.project_name}
                          </td>
                          <td className="max-w-[140px] truncate px-3 py-2.5 text-ink-2">
                            {run.agent_name}
                          </td>
                          <td className="px-3 py-2.5">
                            <code className="rounded bg-surface-2 px-1.5 py-0.5 text-xs text-ink-2">
                              {run.version_label}
                            </code>
                          </td>
                          <td className="px-3 py-2.5">
                            <Badge tone={STATUS_TONE[run.status] ?? "neutral"}>{run.status}</Badge>
                          </td>
                          <td className="px-3 py-2.5">{verdictLabel(run)}</td>
                          <td className="px-5 py-2.5 text-right text-xs text-ink-3">
                            {run.completed_at
                              ? relativeTime(run.completed_at)
                              : relativeTime(run.created_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>

            {/* ---- Performance Overview + Verdict Distribution ---------- */}
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <Card elevation="raised">
                <h2 className="text-sm font-semibold text-ink">Performance Overview</h2>
                <p className="mt-0.5 text-xs text-ink-3">
                  Pass rate per day — last {performanceQuery.data?.range_days ?? 7} days.
                </p>
                {performanceQuery.isLoading && <Skeleton className="mt-4 h-32" />}
                {performanceQuery.data && performanceQuery.data.points.length === 0 && (
                  <div className="mt-3">
                    <EmptyState
                      icon={<ClockIcon />}
                      title="No completed runs yet"
                      description="This chart fills in as suite runs complete — no data is ever invented here."
                    />
                  </div>
                )}
                {performanceQuery.data && performanceQuery.data.points.length > 0 && (
                  <div className="relative mt-4 flex h-32 items-end gap-1.5">
                    {/* Subtle reference gridlines (25/50/75%) — pure
                        decoration, drawn once behind the real bars, never
                        a second data series. */}
                    <div className="pointer-events-none absolute inset-0" aria-hidden="true">
                      <div className="absolute top-0 right-0 left-0 border-t border-line" />
                      <div className="absolute top-1/4 right-0 left-0 border-t border-line/60" />
                      <div className="absolute top-1/2 right-0 left-0 border-t border-line/60" />
                      <div className="absolute top-3/4 right-0 left-0 border-t border-line/60" />
                    </div>
                    {performanceQuery.data.points.map((point) => (
                      <div
                        key={point.date}
                        className="group relative flex h-full flex-1 flex-col justify-end overflow-hidden rounded-sm bg-surface-2"
                        title={`${point.date}: ${Math.round(point.pass_rate * 100)}% pass (${point.total_results} results)`}
                      >
                        <div
                          className="w-full bg-danger/70"
                          style={{ height: `${point.fail_rate * 100}%` }}
                        />
                        <div
                          className="w-full bg-warning/70"
                          style={{ height: `${point.inconclusive_rate * 100}%` }}
                        />
                        <div
                          className="w-full bg-success"
                          style={{ height: `${point.pass_rate * 100}%` }}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </Card>

              <Card elevation="raised">
                <h2 className="text-sm font-semibold text-ink">Verdict Distribution</h2>
                <p className="mt-0.5 text-xs text-ink-3">Across every evaluated test case.</p>
                <div className="mt-4">
                  {verdictQuery.isLoading ? (
                    <Skeleton className="h-28" />
                  ) : (
                    <VerdictDonut
                      pass={verdictQuery.data?.pass_count ?? 0}
                      fail={verdictQuery.data?.fail_count ?? 0}
                      inconclusive={verdictQuery.data?.inconclusive_count ?? 0}
                    />
                  )}
                </div>
              </Card>
            </div>
          </div>

          {/* ---- Right rail: Quick Actions + Recent Activity ------------ */}
          <div className="flex flex-col gap-6">
            <Card elevation="raised">
              <h2 className="text-sm font-semibold text-ink">Quick Actions</h2>
              <div className="mt-3 flex flex-col gap-2">
                <QuickAction
                  icon={<ProjectsIcon />}
                  label="New Project"
                  href="/projects"
                  primary
                />
                <QuickAction icon={<RunsIcon />} label="Run Test Suite" href="/test-suites" />
                <QuickAction icon={<AgentIcon />} label="Add Agent" href="/agents" />
                <QuickAction
                  icon={<TestSuitesIcon />}
                  label="Create Test Case"
                  href="/test-suites"
                />
              </div>
            </Card>

            <Card elevation="raised" padded={false} className="overflow-hidden">
              <div className="flex items-center justify-between border-b border-line px-5 py-4">
                <h2 className="text-sm font-semibold text-ink">Recent Activity</h2>
              </div>
              {activityQuery.isLoading && (
                <div className="flex flex-col gap-3 p-5">
                  <Skeleton className="h-10" />
                  <Skeleton className="h-10" />
                </div>
              )}
              {activityQuery.data && activityQuery.data.length === 0 && (
                <div className="p-5">
                  <EmptyState
                    icon={<InboxIcon />}
                    title="No activity yet"
                    description="Real product events — suite runs, release-gate decisions, AutoFix proposals — show up here as they happen."
                  />
                </div>
              )}
              {activityQuery.data && activityQuery.data.length > 0 && (
                <ul className="flex flex-col divide-y divide-line">
                  {activityQuery.data.map((event: ActivityEventRead) => (
                    <li key={event.id} className="flex items-start gap-3 px-5 py-3.5">
                      <span
                        className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${STAT_TONE_CLASSES[activityTone(event)].chip}`}
                      >
                        {ACTIVITY_ICON[event.event_type] ?? <InboxIcon />}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium text-ink">{event.title}</p>
                        {event.description && (
                          <p className="mt-0.5 line-clamp-2 text-xs text-ink-3">
                            {event.description}
                          </p>
                        )}
                        <p className="mt-1 text-[11px] text-ink-3">
                          {relativeTime(event.created_at)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      </div>
    </AppShell>
  );
}
