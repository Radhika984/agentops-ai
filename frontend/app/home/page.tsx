"use client";

import { useState, useSyncExternalStore, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { AppShell } from "../components/AppShell";
import { Badge, type Tone } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Skeleton } from "../components/ui/Skeleton";
import { STATUS_META, StatusBadge, TONE_CHIP_CLASSES, type StatusKey } from "../components/ui/Status";
import {
  AgentIcon,
  ApprovalsIcon,
  ArrowRightIcon,
  BrandMark,
  CostIcon,
  InboxIcon,
  MonitoringIcon,
  ProjectsIcon,
  ReleaseIcon,
  RunsIcon,
  TestSuitesIcon,
  ToolsIcon,
  VerifyIcon,
} from "../components/ui/icons";
import {
  clearToken,
  getCurrentUser,
  getDashboardStats,
  getPerformanceOverview,
  getRecentSuiteRuns,
  getVerdictDistribution,
  listActivity,
  listApprovals,
  type ActivityEventRead,
  type DashboardStats,
  type SuiteRunSummary,
} from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

// Same env var the landing page's own backend health check reads from
// (app/page.tsx) — reused here, not a new config surface.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

function timeOfDayForHour(hour: number): string {
  if (hour < 5) return "Good night";
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  if (hour < 21) return "Good evening";
  return "Good night";
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
let cachedHour = -1;
let cachedTimeOfDay = timeOfDayForHour(0);

function getTimeOfDaySnapshot(): string {
  const hour = new Date().getHours();
  if (hour !== cachedHour) {
    cachedHour = hour;
    cachedTimeOfDay = timeOfDayForHour(hour);
  }
  return cachedTimeOfDay;
}

function getServerTimeOfDaySnapshot(): string | null {
  return null;
}

function subscribeNever(): () => void {
  return () => {};
}

function useTimeOfDay(): string | null {
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

// Extremely subtle per-EVENT-TYPE icon tint — a category identity, not a
// verdict (the row's actual outcome is the real STATUS_META badge on the
// right, see activityStatusKey below). Soft tints only, matching the
// metric strip's "colored light under dark glass" language rather than a
// saturated fill.
const ACTIVITY_CATEGORY_CLASSES: Record<string, string> = {
  suite_run_completed: "bg-accent-teal-soft text-accent-teal",
  release_gate_evaluated: "bg-accent-category-red-soft text-accent-category-red",
  autofix_proposed: "bg-accent-soft text-accent",
  approval_decided: "bg-accent-violet-soft text-accent-violet",
  agent_version_created: "bg-accent-blue-soft text-accent-blue",
  agent_version_promoted: "bg-accent-blue-soft text-accent-blue",
};

/** The event's real, already-persisted outcome, expressed as one of the
 * app's own STATUS_META keys — rendered via the same <StatusBadge/> used
 * everywhere else a verdict/decision is shown. Returns null (no badge,
 * just the plain row) for event types with no pass/fail/decision meaning
 * of their own (AutoFix proposals, version created/promoted). */
function activityStatusKey(event: ActivityEventRead): StatusKey | null {
  const meta = event.event_metadata;
  switch (event.event_type) {
    case "suite_run_completed": {
      const failCount = Number(meta.fail_count ?? 0);
      const inconclusiveCount = Number(meta.inconclusive_count ?? 0);
      if (failCount > 0) return "FAIL";
      if (inconclusiveCount > 0) return "INCONCLUSIVE";
      return "PASS";
    }
    case "release_gate_evaluated":
      return meta.decision === "hold" ? "HOLD" : "PASS";
    case "approval_decided":
      return meta.approved === true ? "APPROVED" : "REJECTED";
    default:
      return null;
  }
}

/** A one-line, real description for a suite-run activity row — "12 checks"
 * is pass+fail+inconclusive from the event's own persisted metadata, never
 * invented. Falls back to the event's own description for every other
 * event type. */
function activityDescription(event: ActivityEventRead): string | null {
  if (event.event_type === "suite_run_completed") {
    const meta = event.event_metadata;
    const total =
      Number(meta.pass_count ?? 0) + Number(meta.fail_count ?? 0) + Number(meta.inconclusive_count ?? 0);
    if (total > 0) return `Evaluation completed · ${total} check${total === 1 ? "" : "s"}`;
  }
  return event.description;
}

const ACTIVITY_TABS = [
  { key: "all", label: "All", eventTypes: null },
  { key: "runs", label: "Runs", eventTypes: ["suite_run_completed"] },
  { key: "evaluations", label: "Evaluations", eventTypes: ["suite_run_completed"] },
  { key: "releases", label: "Releases", eventTypes: ["release_gate_evaluated"] },
  { key: "approvals", label: "Approvals", eventTypes: ["approval_decided"] },
] as const;

interface AttentionItem {
  count: number;
  label: string;
  href: string;
  status: StatusKey;
  icon: (props: { className?: string }) => ReactNode;
}

/** Every count here comes from data this page already fetches for other
 * widgets (DashboardStats' release_gate_holds, the same pending-approvals
 * call AppShell's notification bell makes, and the already-fetched
 * recent-activity feed's own real event_metadata) — nothing new is
 * queried and nothing is invented to fill this cluster. Each item's icon
 * is the exact glyph STATUS_META already uses for that same real outcome
 * (PENDING/HOLD/INCONCLUSIVE) — reused for visual variety, not a new
 * decorative icon set. */
function attentionItems(
  pendingApprovals: number,
  releaseHolds: number,
  inconclusiveRuns: number,
): AttentionItem[] {
  const items: AttentionItem[] = [];
  if (pendingApprovals > 0) {
    items.push({
      count: pendingApprovals,
      label: `pending approval${pendingApprovals === 1 ? "" : "s"}`,
      href: "/approvals",
      status: "PENDING",
      icon: STATUS_META.PENDING.icon,
    });
  }
  if (releaseHolds > 0) {
    items.push({
      count: releaseHolds,
      label: `release ${releaseHolds === 1 ? "hold" : "holds"}`,
      href: "/release-gate",
      status: "HOLD",
      icon: STATUS_META.HOLD.icon,
    });
  }
  if (inconclusiveRuns > 0) {
    items.push({
      count: inconclusiveRuns,
      label: `inconclusive evaluation${inconclusiveRuns === 1 ? "" : "s"}`,
      href: "/evaluation",
      status: "INCONCLUSIVE",
      icon: STATUS_META.INCONCLUSIVE.icon,
    });
  }
  return items;
}

function verdictLabel(run: SuiteRunSummary): ReactNode {
  if (run.status !== "completed" && run.status !== "failed") {
    return <Badge tone={STATUS_TONE[run.status] ?? "neutral"}>{run.status}</Badge>;
  }
  if (!run.verdict) return <span className="text-ink-3">—</span>;
  return <StatusBadge status={run.verdict as StatusKey} />;
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

interface LifecycleStage {
  key: string;
  label: string;
  href: string;
  hint: string;
  icon: (props: { className?: string }) => ReactNode;
  noun: string;
  count?: number;
}

/** The product lifecycle, made real: each stage links to its actual page,
 * and shows its actual count where the API has one (DashboardStats only
 * covers agents/suite-runs/release-gate-holds — Version/Contract/
 * Evaluate/Monitor have no account-wide count endpoint, so those render
 * as quiet outlined nodes with a one-line "what this is", never an
 * invented number). Never touches the backend to add the missing
 * counts. */
function buildLifecycleStages(stats: DashboardStats | undefined): LifecycleStage[] {
  return [
    {
      key: "register",
      label: "Register",
      href: "/agents",
      hint: "Add the agent under test.",
      icon: AgentIcon,
      noun: "agents",
      count: stats?.total_agents,
    },
    {
      key: "version",
      label: "Version",
      href: "/agents",
      hint: "Point a version at your agent.",
      icon: TestSuitesIcon,
      noun: "versions",
    },
    {
      key: "contract",
      label: "Contract",
      href: "/test-suites",
      hint: "Define what it must do.",
      icon: ProjectsIcon,
      noun: "test suites",
    },
    {
      key: "run",
      label: "Run",
      href: "/runs",
      hint: "Execute the suite.",
      icon: RunsIcon,
      noun: "runs",
      count: stats?.total_suite_runs,
    },
    {
      key: "evaluate",
      label: "Evaluate",
      href: "/evaluation",
      hint: "Review the verdicts.",
      icon: VerifyIcon,
      noun: "evaluations",
    },
    {
      key: "gate",
      label: "Gate",
      href: "/release-gate",
      hint: "Decide: ship or hold.",
      icon: ReleaseIcon,
      noun: "releases",
      count: stats?.release_gate_holds,
    },
    {
      key: "monitor",
      label: "Monitor",
      href: "/monitoring",
      hint: "Watch it in production.",
      icon: MonitoringIcon,
      noun: "active",
    },
  ];
}

function LifecycleRail({ stats, loading }: { stats: DashboardStats | undefined; loading: boolean }) {
  const stages = buildLifecycleStages(stats);
  // "Furthest reached" = the last stage with a real, positive count —
  // never inferred from a stage that has no data of its own.
  let furthestIndex = -1;
  stages.forEach((stage, i) => {
    if (typeof stage.count === "number" && stage.count > 0) furthestIndex = i;
  });

  return (
    <Card elevation="raised" padded={false} className="overflow-hidden">
      <div className="flex items-start gap-0 overflow-x-auto px-5 py-6">
        {stages.map((stage, i) => {
          const Icon = stage.icon;
          const hasCount = typeof stage.count === "number";
          const reached = i <= furthestIndex;
          return (
            <div key={stage.key} className="relative flex items-start">
              {i > 0 && (
                <div
                  className={`animate-line-draw relative mt-6 h-px w-6 shrink-0 origin-left sm:w-10 ${i <= furthestIndex ? "bg-accent" : "bg-line-strong"}`}
                  style={{ animationDelay: `${700 + i * 90}ms` }}
                  aria-hidden="true"
                >
                  <span className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 text-[10px] text-ink-3">
                    ›
                  </span>
                </div>
              )}
              <Link
                href={stage.href}
                className="animate-fade-in-up group flex w-24 shrink-0 flex-col items-center gap-2 rounded-control px-1 py-1 text-center no-underline sm:w-28"
                style={{ animationDelay: `${750 + i * 90}ms` }}
              >
                {loading ? (
                  <Skeleton className="h-12 w-12 rounded-full" />
                ) : (
                  <span
                    className={`flex h-12 w-12 items-center justify-center rounded-full border text-ink-2 transition-all duration-200 group-hover:scale-105 ${
                      reached
                        ? "border-accent/60 bg-accent-soft text-accent shadow-[0_0_16px_2px_rgba(217,128,74,0.35)] group-hover:shadow-[0_0_22px_4px_rgba(217,128,74,0.5)]"
                        : "border-line-strong bg-surface-2 group-hover:border-accent/40 group-hover:text-accent"
                    }`}
                  >
                    <Icon />
                  </span>
                )}
                <span className="text-[11px] font-semibold tracking-[0.06em] text-ink uppercase">
                  {stage.label}
                </span>
                {hasCount ? (
                  <span className="text-[11px] leading-tight text-ink-3 tabular-nums">
                    {stage.count} {stage.noun}
                  </span>
                ) : (
                  <span className="text-[11px] leading-tight text-ink-3">{stage.hint}</span>
                )}
              </Link>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

// Fixed (never randomized) decorative star positions — stable across
// renders, purely atmospheric. Percent coordinates within the hero panel.
const HERO_STARS = [
  { top: 8, left: 30, size: 2 },
  { top: 14, left: 62, size: 1.5 },
  { top: 22, left: 78, size: 2 },
  { top: 34, left: 48, size: 1 },
  { top: 12, left: 90, size: 1.5 },
  { top: 28, left: 20, size: 1 },
  { top: 44, left: 85, size: 1.5 },
  { top: 6, left: 55, size: 1 },
];

/** Decorative cinematic hero backdrop — one continuous environment (base
 * glow, mountain silhouette, starfield, glowing core, orbital lines to
 * the seven lifecycle stages) built from CSS gradients/box-shadow and
 * inline SVG only (no image asset, no new dependency). It is a single
 * absolutely-positioned layer behind the whole hero section, not a boxed
 * illustration next to the text — the headline sits on top of it. Purely
 * illustrative (aria-hidden) — no data is represented here, only the
 * product's own real lifecycle labels. */
function HeroEnvironment() {
  const SIZE = 640;
  const CENTER_X = SIZE * 0.69;
  const CENTER_Y = SIZE * 0.42;
  const nodes: {
    Icon: (props: { className?: string; width?: number; height?: number }) => ReactNode;
    label: string;
    xPct: number;
    yPct: number;
    delay: string;
  }[] = [
    { Icon: VerifyIcon, label: "Evaluate", xPct: 70, yPct: 12, delay: "0s" },
    { Icon: RunsIcon, label: "Run", xPct: 86, yPct: 26, delay: "1.3s" },
    { Icon: ReleaseIcon, label: "Gate", xPct: 86, yPct: 58, delay: "2.6s" },
    { Icon: MonitoringIcon, label: "Monitor", xPct: 70, yPct: 72, delay: "3.9s" },
    { Icon: ProjectsIcon, label: "Contract", xPct: 52, yPct: 58, delay: "5.2s" },
    { Icon: AgentIcon, label: "Register", xPct: 52, yPct: 26, delay: "6.5s" },
  ];

  // A sparse set of particles traveling along the orbit rings — each is a
  // fixed point at a given radius/angle, carried around by the SAME
  // Each particle gets its OWN rotation speed/direction (8-12s, per the
  // "different nodes different speeds... organic motion" brief) rather
  // than sharing its ring's exact rotation — small variation per particle
  // is what reads as "actually traveling" instead of a mechanically
  // uniform loop. Fades in/out over the lap so it reads as a moving
  // light, not a static dot. Kept sparse (9 total) per "not a starfield".
  const PARTICLES: { radius: number; angle: number; duration: number; reverse?: boolean }[] = [
    { radius: 170, angle: 20, duration: 12 },
    { radius: 170, angle: 140, duration: 10, reverse: true },
    { radius: 170, angle: 260, duration: 11 },
    { radius: 125, angle: 60, duration: 9, reverse: true },
    { radius: 125, angle: 180, duration: 10 },
    { radius: 125, angle: 300, duration: 8.5, reverse: true },
    { radius: 88, angle: 90, duration: 8 },
    { radius: 88, angle: 270, duration: 9, reverse: true },
    { radius: 88, angle: 0, duration: 7.5 },
  ];

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden" aria-hidden="true">
      {/* Layers 1-2: near-black base + warm horizon glow (the light source
          the whole scene is lit by), drifting almost imperceptibly so the
          atmosphere reads as alive rather than a static image. */}
      <div className="animate-atmosphere-drift absolute -inset-8">
        <div
          className="absolute inset-0"
          style={{
            background:
              "linear-gradient(180deg, color-mix(in srgb, var(--accent) 5%, transparent) 0%, transparent 45%)",
          }}
        />
        <div
          className="absolute inset-0"
          style={{
            background:
              "radial-gradient(ellipse 55% 65% at 70% 46%, color-mix(in srgb, var(--accent) 30%, transparent) 0%, transparent 60%), radial-gradient(ellipse 90% 40% at 80% 100%, color-mix(in srgb, var(--accent) 16%, transparent) 0%, transparent 72%)",
          }}
        />
      </div>

      {/* A single, quiet band of light crossing the hero left-to-right —
          cinematic haze, not a loading-bar sweep. Rotated container keeps
          the sweep's own motion (translateX, from the keyframe) from
          fighting the diagonal tilt (a separate, static transform). */}
      <div className="absolute inset-[-20%] rotate-[-10deg] overflow-hidden">
        <div
          className="animate-light-sweep absolute inset-y-0 w-1/3"
          style={{
            background:
              "linear-gradient(90deg, transparent 0%, color-mix(in srgb, var(--accent-bright) 70%, transparent) 50%, transparent 100%)",
          }}
        />
      </div>

      {HERO_STARS.map((star, i) => (
        <span
          key={i}
          className="absolute rounded-full bg-ink-2/60"
          style={{ top: `${star.top}%`, left: `${star.left}%`, width: star.size, height: star.size }}
        />
      ))}

      {/* Layer 3: distant terrain silhouette — smooth rolling ridgeline,
          not a sharp zig-zag, lit from behind by the horizon glow. */}
      <svg
        viewBox="0 0 1000 200"
        preserveAspectRatio="none"
        className="absolute inset-x-0 bottom-0 h-28 w-full opacity-80 md:h-36"
      >
        <path
          d="M0 200 L0 150 C120 120 180 160 260 130 C360 95 420 150 520 115 C620 85 700 130 800 100 C880 78 940 110 1000 90 L1000 200 Z"
          fill="var(--background)"
        />
      </svg>

      {/* Layer 4: nearer, darker foreground terrain — the second depth
          plane that sells "space behind the interface". */}
      <svg
        viewBox="0 0 1000 160"
        preserveAspectRatio="none"
        className="absolute inset-x-0 bottom-0 h-16 w-full md:h-20"
      >
        <path
          d="M0 160 L0 110 C150 90 250 125 380 100 C520 72 640 115 760 95 C860 78 930 100 1000 85 L1000 160 Z"
          fill="var(--background)"
        />
      </svg>

      {/* Layers 5-7: the AI object + orbital system, biased to the upper
          right so the composition reads as one wide environment rather
          than a centered badge. Fades in, then begins rotating — never
          appears already mid-spin. */}
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        preserveAspectRatio="none"
        className="animate-fade-in absolute inset-0 hidden h-full w-full lg:block"
        style={{ animationDelay: "500ms" }}
      >
        {nodes.map((n, i) => {
          const x2 = (n.xPct / 100) * SIZE;
          const y2 = (n.yPct / 100) * SIZE;
          return (
            <g key={i}>
              <line
                x1={CENTER_X}
                y1={CENTER_Y}
                x2={x2}
                y2={y2}
                stroke="var(--accent)"
                strokeOpacity="0.3"
                strokeWidth="1"
              />
              <circle cx={x2} cy={y2} r={2.5} fill="var(--accent)" fillOpacity="0.65" />
            </g>
          );
        })}
        <circle cx={CENTER_X} cy={CENTER_Y} r={170} fill="none" stroke="var(--line)" strokeWidth="1" />
        <circle cx={CENTER_X} cy={CENTER_Y} r={125} fill="none" stroke="var(--line)" strokeWidth="1" />
        <circle
          cx={CENTER_X}
          cy={CENTER_Y}
          r={88}
          fill="none"
          stroke="var(--accent)"
          strokeOpacity="0.3"
          strokeWidth="1"
          strokeDasharray="2 8"
          className="animate-orbit-spin-fast"
          style={{ transformOrigin: `${CENTER_X}px ${CENTER_Y}px` }}
        />
        {/* Sparse traveling light particles — each gets its own rotation
            speed/direction (a <g> wrapper animated by inline style, since
            the duration varies continuously per particle rather than
            matching a fixed Tailwind utility), carrying one fixed-radius
            dot that fades in and out over the lap so it reads as an
            actually-moving light, not a starfield. */}
        {PARTICLES.map((p, i) => {
          const rad = (p.angle * Math.PI) / 180;
          const px = CENTER_X + p.radius * Math.cos(rad);
          const py = CENTER_Y + p.radius * Math.sin(rad);
          return (
            <g
              key={i}
              style={{
                transformOrigin: `${CENTER_X}px ${CENTER_Y}px`,
                animation: `${p.reverse ? "orbit-spin-reverse" : "orbit-spin"} ${p.duration}s linear infinite`,
              }}
            >
              <circle
                cx={px}
                cy={py}
                r={2}
                fill="var(--accent-bright)"
                className="animate-particle-fade"
                style={{ animationDelay: `${i * 0.7}s` }}
              />
            </g>
          );
        })}
      </svg>

      {/* The central light — a soft breathing glow sitting behind the
          object, animated independently of it. Two animations on one
          element (a one-shot entrance plus the continuous breathe) are
          combined via the inline `animation` shorthand directly — two
          separate `animate-*` utility classes can't be stacked, since
          each sets the whole shorthand and the later one would simply
          clobber the first. */}
      <div
        className="absolute h-44 w-44 -translate-x-1/2 -translate-y-1/2 rounded-full md:h-56 md:w-56"
        style={{
          left: `${(CENTER_X / SIZE) * 100}%`,
          top: `${(CENTER_Y / SIZE) * 100}%`,
          background: "radial-gradient(circle at 50% 50%, color-mix(in srgb, var(--accent) 35%, transparent) 0%, transparent 70%)",
          animation: "fade-in 0.5s ease-out 300ms both, core-glow 4s ease-in-out infinite",
        }}
      />

      {/* The central AI object — a dark glossy sphere with warm internal
          illumination and a thin gold rim light, not a flat bright ball.
          Floats independently of the glow behind it. */}
      <div
        className="absolute h-28 w-28 -translate-x-1/2 -translate-y-1/2 rounded-full md:h-36 md:w-36"
        style={{
          left: `${(CENTER_X / SIZE) * 100}%`,
          top: `${(CENTER_Y / SIZE) * 100}%`,
          boxShadow: "0 0 90px 18px color-mix(in srgb, var(--accent) 22%, transparent)",
          animation: "fade-in 0.5s ease-out 300ms both, core-float 4.5s ease-in-out infinite",
        }}
      >
        <div
          className="absolute inset-0 rounded-full"
          style={{
            background: "radial-gradient(circle at 36% 30%, #2a241c 0%, #15110c 55%, #0a0806 100%)",
            boxShadow:
              "inset 0 0 0 1px color-mix(in srgb, var(--accent) 45%, transparent), inset -6px -8px 20px rgba(0,0,0,0.6), inset 6px 6px 18px color-mix(in srgb, var(--accent) 18%, transparent)",
          }}
        />
        <span
          className="absolute inset-0 rounded-full"
          style={{
            background:
              "conic-gradient(from 210deg at 50% 50%, color-mix(in srgb, var(--accent) 55%, transparent), transparent 35%, transparent 65%, color-mix(in srgb, var(--accent) 35%, transparent))",
            mixBlendMode: "screen",
            opacity: 0.5,
          }}
        />
        <span className="absolute inset-0 flex items-center justify-center text-accent-bright">
          <span className="drop-shadow-[0_0_10px_rgba(232,199,122,0.6)]">
            <BrandMark width={26} height={26} />
          </span>
        </span>
      </div>

      {nodes.map(({ Icon, label, xPct, yPct, delay }, i) => (
        <span
          key={i}
          className="absolute hidden -translate-x-1/2 -translate-y-1/2 items-center gap-1.5 rounded-full border border-line-strong bg-surface-elevated/90 py-1.5 pr-3.5 pl-1.5 text-xs font-medium whitespace-nowrap text-ink shadow-[0_4px_20px_-4px_rgba(232,199,122,0.25)] lg:flex"
          style={{
            left: `${xPct}%`,
            top: `${yPct}%`,
            // Two animations on one element (a one-shot mount stagger plus
            // the continuous float) combined via the inline shorthand —
            // see the central light/object comment above for why two
            // `animate-*` classes can't be stacked here instead.
            animation: `fade-in 0.5s ease-out ${650 + i * 70}ms both, float-slow 7s ease-in-out infinite ${delay}`,
          }}
        >
          <span
            className="animate-node-breathe flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
            style={{ animationDelay: `${i * 0.7}s` }}
          >
            <Icon width={13} height={13} />
          </span>
          {label}
        </span>
      ))}

      {/* Reference's right-edge marketing line — real brand copy, not a
          data claim, shown only when there's room for it. */}
      <div className="absolute top-[6%] right-6 hidden w-36 text-right text-[10px] leading-relaxed font-medium tracking-[0.1em] text-ink-2 uppercase xl:block">
        A safer, higher standard for a brighter AI future.
      </div>
    </div>
  );
}

// Decorative per-metric "category" identity — jewel-tone light under dark
// glass, deliberately a SEPARATE system from --accent (champagne, the
// hero/sidebar/lifecycle signature) and from STATUS_META's semantic
// colors (never reassigned to a verdict). Each metric keeps its own
// identity color across icon, border tint, radial glow and micro-chart —
// the thing the reference's metric row has that a single shared accent
// can't express.
type MetricCategory = "violet" | "blue" | "teal" | "red";

const METRIC_CATEGORY_CLASSES: Record<
  MetricCategory,
  { icon: string; border: string; stroke: string; glow: string }
> = {
  violet: {
    icon: "bg-accent-violet-soft text-accent-violet",
    border: "border-accent-violet/45",
    stroke: "var(--accent-violet)",
    glow: "var(--accent-violet)",
  },
  blue: {
    icon: "bg-accent-blue-soft text-accent-blue",
    border: "border-accent-blue/45",
    stroke: "var(--accent-blue)",
    glow: "var(--accent-blue)",
  },
  teal: {
    icon: "bg-accent-teal-soft text-accent-teal",
    border: "border-accent-teal/45",
    stroke: "var(--accent-teal)",
    glow: "var(--accent-teal)",
  },
  red: {
    icon: "bg-accent-category-red-soft text-accent-category-red",
    border: "border-accent-category-red/45",
    stroke: "var(--accent-category-red)",
    glow: "var(--accent-category-red)",
  },
};

interface MetricDef {
  key: string;
  label: string;
  value: number | undefined;
  loading: boolean;
  isError: boolean;
  href: string;
  icon: ReactNode;
  category: MetricCategory;
  hint?: string;
  /** Real values only, oldest first (e.g. per-day pass rate, per-run pass
   * rate) — never fabricated. `undefined`/fewer than 2 points means this
   * metric has no real time series behind it (DashboardStats only has a
   * point-in-time count), and the tile renders an honest flat baseline
   * instead of inventing a trend. */
  series?: number[];
}

/** Plots the metric's own real series (a 0-28 viewBox polyline, gradient
 * fill under a thin rounded line — no axes/gridlines/labels, per a
 * single-series sparkline's spec) when at least two real points exist.
 * With no real series, draws a quiet flat baseline instead of a fake
 * trend shape — "no data" must never be dressed up as "a trend of zero
 * change." */
function MetricSparkline({ id, stroke, series }: { id: string; stroke: string; series?: number[] }) {
  const hasSeries = !!series && series.length >= 2;
  const min = hasSeries ? Math.min(...series!) : 0;
  const max = hasSeries ? Math.max(...series!) : 1;
  const span = max - min || 1;
  const points = hasSeries
    ? series!.map((v, i) => {
        const x = (i / (series!.length - 1)) * 100;
        const y = 24 - ((v - min) / span) * 20;
        return [x, y] as const;
      })
    : [];
  const linePath = hasSeries
    ? points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x} ${y}`).join(" ")
    : "M0 22 L100 22";
  const areaPath = hasSeries ? `${linePath} L100 28 L0 28 Z` : "";

  return (
    <svg viewBox="0 0 100 28" preserveAspectRatio="none" className="h-6 w-full" aria-hidden="true">
      {hasSeries ? (
        <>
          <defs>
            <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={stroke} stopOpacity="0.45" />
              <stop offset="100%" stopColor={stroke} stopOpacity="0" />
            </linearGradient>
          </defs>
          <path d={areaPath} fill={`url(#${id})`} stroke="none" />
          <path
            d={linePath}
            fill="none"
            stroke={stroke}
            strokeOpacity="1"
            strokeWidth="1.75"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </>
      ) : (
        // No real series behind this metric — a quiet, honest baseline
        // (dashed, low-opacity) rather than a trend that doesn't exist.
        <path d={linePath} fill="none" stroke="var(--line-strong)" strokeWidth="1" strokeDasharray="2 3" />
      )}
    </svg>
  );
}

/** Compact KPI tile for the metric strip — "black glass with colored
 * light underneath": a very dark card, a subtle category-tinted corner
 * glow and border, never a filled block of color. The number itself is
 * always the caller's real, already-fetched value — "—" on error, never
 * a placeholder digit. */
function MetricTile({ metric, index }: { metric: MetricDef; index: number }) {
  const cat = METRIC_CATEGORY_CLASSES[metric.category];
  return (
    <Link
      href={metric.href}
      className="group animate-fade-in-up block rounded-surface no-underline focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/25"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      <Card
        elevation="raised"
        className={`relative flex h-28 flex-col justify-between overflow-hidden border transition-all duration-200 group-hover:-translate-y-0.5 ${cat.border}`}
      >
        <div
          className="pointer-events-none absolute inset-0 opacity-80 transition-opacity duration-200 group-hover:opacity-100"
          style={{
            background: `radial-gradient(ellipse 90% 80% at 100% 100%, color-mix(in srgb, ${cat.glow} 30%, transparent) 0%, transparent 70%)`,
          }}
          aria-hidden="true"
        />
        <div className="relative flex items-center justify-between">
          <span className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-control ${cat.icon}`}>
            {metric.icon}
          </span>
          <ArrowRightIcon className="shrink-0 text-ink-3 opacity-0 transition-opacity duration-150 group-hover:opacity-100" />
        </div>
        <div className="relative">
          <p className="text-[11px] font-medium tracking-wide text-ink-3 uppercase">{metric.label}</p>
          {metric.loading ? (
            <Skeleton className="mt-1 h-7 w-12" />
          ) : (
            <>
              <p className="mt-0.5 text-3xl font-bold tracking-tight text-ink tabular-nums">
                {metric.isError ? "—" : (metric.value ?? "—")}
              </p>
              {metric.hint && !metric.isError && (
                <p className="truncate text-[11px] text-ink-3">{metric.hint}</p>
              )}
            </>
          )}
        </div>
        <div className="relative">
          <MetricSparkline id={`spark-${metric.key}`} stroke={cat.stroke} series={metric.series} />
        </div>
      </Card>
    </Link>
  );
}

type HealthRowState = "ok" | "degraded" | "checking" | "unknown";

function SystemHealthRow({
  label,
  state,
  detail,
  series,
}: {
  label: string;
  state: HealthRowState;
  detail: string;
  /** Real, session-observed values only (e.g. actually-measured API
   * latencies from repeated pings) — never a fabricated trend. Omitted
   * for rows with no plottable real metric (Database/Evaluation
   * Engine/Workers only have a reachable/unreachable state, not a
   * number). */
  series?: number[];
}) {
  const dotClass =
    state === "ok"
      ? "bg-success text-success"
      : state === "degraded"
        ? "bg-danger text-danger"
        : state === "checking"
          ? "bg-accent text-accent"
          : "bg-ink-3 text-ink-3";
  return (
    <div className="flex items-center justify-between gap-3 px-5 py-2.5">
      <span className="flex items-center gap-2.5 text-sm text-ink">
        <span className={`h-2 w-2 shrink-0 rounded-full ${dotClass} shadow-[0_0_6px_1px_currentColor]`} aria-hidden="true" />
        {label}
      </span>
      <span className="flex items-center gap-2 text-xs text-ink-3">
        {series && series.length >= 2 && (
          <span className="h-4 w-12">
            <MetricSparkline id={`health-${label}`} stroke="var(--accent-teal)" series={series} />
          </span>
        )}
        {detail}
        <ArrowRightIcon className="h-3 w-3 shrink-0 opacity-50" />
      </span>
    </div>
  );
}

/** System Health — genuinely truthful, not a decorative uptime board.
 * "API" pings the same real /api/v1/health endpoint the public landing
 * page already checks (app/page.tsx), and reports its own measured
 * round-trip latency. "Database" and "Evaluation Engine" are honest
 * proxies: they reflect whether the dashboard-stats / verdict-distribution
 * queries (which must round-trip through the DB and the evaluation
 * pipeline respectively) actually succeeded — real signal, not a fake
 * percentage. "Workers" has no backing endpoint anywhere in this app, so
 * it's shown as a frank "No data" row rather than an invented number. */
function SystemHealthPanel({
  statsOk,
  statsLoading,
  statsError,
  verdictOk,
  verdictLoading,
  verdictError,
}: {
  statsOk: boolean;
  statsLoading: boolean;
  statsError: boolean;
  verdictOk: boolean;
  verdictLoading: boolean;
  verdictError: boolean;
}) {
  const healthQuery = useQuery({
    queryKey: ["system", "health"],
    queryFn: async () => {
      const start = performance.now();
      const res = await fetch(`${API_URL}/api/v1/health`);
      if (!res.ok) throw new Error(`status ${res.status}`);
      return { ms: Math.round(performance.now() - start) };
    },
    staleTime: 0,
    // Re-pings periodically so the latency sparkline below is built from
    // genuinely repeated real measurements, not a single point stretched
    // into a fake trend.
    refetchInterval: 8000,
    retry: false,
  });

  // A rolling window of this session's own real measured latencies — never
  // historical/server-side data (no such endpoint exists), just an honest
  // record of what was actually observed while this page has been open.
  // Tracks "last seen" in state (not a ref) and updates conditionally
  // during render — React's own documented "storing information from
  // previous renders" pattern — rather than a useEffect, since a ref
  // read/write during render and a setState-in-effect are both
  // disallowed under this project's React Compiler-aligned lint rules.
  const [lastSeenMs, setLastSeenMs] = useState<number | null>(null);
  const [latencyHistory, setLatencyHistory] = useState<number[]>([]);
  if (healthQuery.data?.ms != null && healthQuery.data.ms !== lastSeenMs) {
    setLastSeenMs(healthQuery.data.ms);
    setLatencyHistory((prev) => [...prev, healthQuery.data!.ms].slice(-12));
  }

  const apiState: HealthRowState = healthQuery.isLoading
    ? "checking"
    : healthQuery.isError
      ? "degraded"
      : "ok";
  const dbState: HealthRowState = statsLoading ? "checking" : statsError ? "degraded" : statsOk ? "ok" : "unknown";
  const evalState: HealthRowState = verdictLoading
    ? "checking"
    : verdictError
      ? "degraded"
      : verdictOk
        ? "ok"
        : "unknown";

  const allOperational = apiState === "ok" && dbState === "ok" && evalState === "ok";

  return (
    <Card elevation="raised" padded={false} className="overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <h2 className="text-sm font-semibold text-ink">System Health</h2>
        <span
          className={`inline-flex items-center gap-1.5 rounded-control px-1.5 py-0.5 text-[11px] font-medium ${
            allOperational ? "bg-accent-teal-soft text-accent-teal" : "bg-surface-2 text-ink-2"
          }`}
        >
          {allOperational ? "All Systems Operational" : "Checking…"}
        </span>
      </div>
      <div className="divide-y divide-line">
        <SystemHealthRow
          label="API"
          state={apiState}
          detail={
            healthQuery.isLoading
              ? "Checking…"
              : healthQuery.isError
                ? "Unreachable"
                : `${healthQuery.data?.ms ?? 0} ms`
          }
          series={latencyHistory}
        />
        <SystemHealthRow
          label="Database"
          state={dbState}
          detail={statsLoading ? "Checking…" : statsError ? "Unreachable" : statsOk ? "Reachable" : "No data"}
        />
        <SystemHealthRow
          label="Evaluation Engine"
          state={evalState}
          detail={
            verdictLoading ? "Checking…" : verdictError ? "Unreachable" : verdictOk ? "Reachable" : "No data"
          }
        />
        <SystemHealthRow label="Workers" state="unknown" detail="No data" />
      </div>
    </Card>
  );
}

function PromoCard() {
  return (
    <Card
      elevation="raised"
      padded={false}
      className="card-depth relative overflow-hidden bg-surface-elevated text-ink"
    >
      <div className="relative z-10 p-5">
        <h2 className="font-serif text-xl leading-tight text-ink">
          From experiment
          <br />
          to <em className="text-accent italic">production.</em>
        </h2>
        <p className="mt-2.5 text-xs leading-relaxed text-ink-2">
          A complete lifecycle for AI agents — with safety, evaluation, and human oversight.
        </p>
        <Link
          href="/"
          className="mt-4 inline-flex items-center gap-1.5 text-xs font-semibold text-accent no-underline hover:underline"
        >
          Learn more <ArrowRightIcon />
        </Link>
      </div>
    </Card>
  );
}

export default function HomePage() {
  const router = useRouter();
  const checkedAuth = useRequireAuth();
  const timeOfDay = useTimeOfDay();
  const [activityTab, setActivityTab] = useState<(typeof ACTIVITY_TABS)[number]["key"]>("all");

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
    queryFn: () => listActivity(20),
    enabled: checkedAuth,
  });

  // Same call AppShell's notification bell already makes — reused here,
  // not a new endpoint, so the "needs attention" cluster below is built
  // entirely from data the app already fetches elsewhere.
  const pendingApprovalsQuery = useQuery({
    queryKey: ["approvals", "pending"],
    queryFn: () => listApprovals("pending"),
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

  const attentionLoading = pendingApprovalsQuery.isLoading || statsQuery.isLoading || activityQuery.isLoading;
  const releaseHolds = statsQuery.data?.release_gate_holds ?? 0;
  const pendingApprovalsCount = pendingApprovalsQuery.data?.length ?? 0;
  const inconclusiveRuns = (activityQuery.data ?? []).filter(
    (e) => e.event_type === "suite_run_completed" && Number(e.event_metadata.inconclusive_count ?? 0) > 0,
  ).length;
  const attention = attentionItems(pendingApprovalsCount, releaseHolds, inconclusiveRuns);

  // Real series only — never fabricated. "Test Suite Runs" plots each
  // real recent run's own pass rate (pass_count / total cases), oldest
  // first; "Evaluations" plots the real 7-day pass-rate-per-day series
  // the Performance Overview card below already fetches. Agents/Release
  // Holds have no time series anywhere in DashboardStats (point-in-time
  // counts only), so they intentionally get no `series` — MetricSparkline
  // renders an honest flat baseline for those instead of inventing one.
  const suiteRunSeries = recentRunsQuery.data?.items
    .slice()
    .reverse()
    .map((run) => {
      const total = run.pass_count + run.fail_count + run.inconclusive_count;
      return total > 0 ? run.pass_count / total : 0;
    });
  const evaluationSeries = performanceQuery.data?.points.map((p) => p.pass_rate);

  const metrics: MetricDef[] = [
    {
      key: "agents",
      label: "Agents",
      value: statsQuery.data?.total_agents,
      loading: statsQuery.isLoading,
      isError: statsQuery.isError,
      href: "/agents",
      icon: <AgentIcon />,
      category: "violet",
    },
    {
      key: "suite-runs",
      label: "Test Suite Runs",
      value: statsQuery.data?.total_suite_runs,
      loading: statsQuery.isLoading,
      isError: statsQuery.isError,
      href: "/runs",
      icon: <TestSuitesIcon />,
      category: "blue",
      series: suiteRunSeries,
    },
    {
      key: "evaluations",
      label: "Evaluations",
      value: verdictQuery.data?.total,
      loading: verdictQuery.isLoading,
      isError: verdictQuery.isError,
      href: "/evaluation",
      icon: <VerifyIcon />,
      category: "teal",
      series: evaluationSeries,
    },
    {
      key: "release-holds",
      label: "Release Holds",
      value: statsQuery.data?.release_gate_holds,
      loading: statsQuery.isLoading,
      isError: statsQuery.isError,
      href: "/release-gate",
      icon: <CostIcon />,
      category: "red",
    },
  ];

  const activeTab = ACTIVITY_TABS.find((t) => t.key === activityTab) ?? ACTIVITY_TABS[0];
  const filteredActivity = (activityQuery.data ?? []).filter(
    (e) => activeTab.eventTypes === null || (activeTab.eventTypes as readonly string[]).includes(e.event_type),
  );

  return (
    <AppShell onLogout={handleLogout}>
      <div className="mx-auto w-full max-w-7xl py-6">
        {/* ---- Hero: one continuous cinematic environment, not a text
            card beside an illustration card — the headline sits directly
            over the backdrop, which bleeds edge-to-edge. ---------------- */}
        <div className="relative -mx-4 flex min-h-[22rem] items-center overflow-hidden px-4 py-10 md:-mx-8 md:min-h-[26rem] md:px-8 md:py-14">
          <HeroEnvironment />
          <div className="relative max-w-xl">
            {userQuery.isLoading || !timeOfDay ? (
              <Skeleton className="h-3.5 w-48" />
            ) : (
              displayName && (
                <p
                  className="animate-fade-in-up text-eyebrow text-accent-bright/80 tracking-[0.2em]"
                  style={{ animationDelay: "100ms" }}
                >
                  {timeOfDay.toUpperCase()}, {displayName.toUpperCase()}
                </p>
              )
            )}
            <h1
              className="animate-headline-reveal font-serif mt-4 text-[3rem] leading-[1.05] font-normal text-ink md:text-[4rem]"
              style={{ animationDelay: "180ms" }}
            >
              Turn ideas into
              <br />
              <em className="text-accent italic">trusted AI agents.</em>
            </h1>
            <p className="animate-fade-in-up text-body mt-4 max-w-lg text-ink-2" style={{ animationDelay: "320ms" }}>
              Run, evaluate, and safeguard AI agents — from experiment to production, with confidence.
            </p>
            <div className="animate-fade-in-up mt-6 flex flex-wrap gap-3" style={{ animationDelay: "420ms" }}>
              <Link href="/agents" className="no-underline">
                <Button variant="primary">Run an Agent</Button>
              </Link>
              <Link href="/test-suites" className="no-underline">
                <Button variant="secondary">
                  View Test Suites <ArrowRightIcon />
                </Button>
              </Link>
            </div>
          </div>
        </div>

        <div className="px-4 md:px-8">
        {/* ---- Lifecycle rail — the signature element: every stage is a
            real page, real count where one exists, quiet where it
            doesn't. -------------------------------------------------- */}
        <div className="mt-6">
          <LifecycleRail stats={statsQuery.data} loading={statsQuery.isLoading} />
        </div>

        {/* ---- Metric strip ---------------------------------------------- */}
        <div className="mt-6 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {metrics.map((metric, i) => (
            <MetricTile key={metric.key} metric={metric} index={i} />
          ))}
        </div>

        <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[1fr_340px]">
          <div className="flex flex-col gap-6">
            {/* ---- Recent Activity ---------------------------------------- */}
            <Card elevation="raised" padded={false} className="overflow-hidden">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
                <h2 className="text-sm font-semibold text-ink">Recent Activity</h2>
                <Link
                  href="/runs"
                  className="flex items-center gap-1 text-xs font-medium text-accent no-underline hover:text-accent-hover"
                >
                  View all <ArrowRightIcon />
                </Link>
              </div>
              <div className="flex items-center gap-1 overflow-x-auto border-b border-line px-5 py-2">
                {ACTIVITY_TABS.map((tab) => (
                  <button
                    key={tab.key}
                    onClick={() => setActivityTab(tab.key)}
                    className={`shrink-0 rounded-control px-2.5 py-1 text-xs font-medium transition-colors duration-150 ${
                      activityTab === tab.key
                        ? "bg-accent-soft text-accent"
                        : "text-ink-3 hover:bg-surface-2 hover:text-ink"
                    }`}
                  >
                    {tab.label}
                  </button>
                ))}
              </div>
              {activityQuery.isLoading && (
                <div className="flex flex-col gap-3 p-5">
                  <Skeleton className="h-10" />
                  <Skeleton className="h-10" />
                  <Skeleton className="h-10" />
                </div>
              )}
              {activityQuery.isError && (
                <p className="m-5 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                  Could not load recent activity.
                </p>
              )}
              {activityQuery.data && filteredActivity.length === 0 && (
                <div className="p-5">
                  <EmptyState
                    icon={<InboxIcon />}
                    title="No activity yet"
                    description="Real product events — suite runs, release-gate decisions, AutoFix proposals — show up here as they happen."
                  />
                </div>
              )}
              {activityQuery.data && filteredActivity.length > 0 && (
                <ul className="flex flex-col divide-y divide-line">
                  {filteredActivity.map((event: ActivityEventRead) => {
                    const statusKey = activityStatusKey(event);
                    return (
                      <li
                        key={event.id}
                        className="flex items-start gap-3 px-5 py-3.5 transition-colors duration-200 hover:bg-surface"
                      >
                        <span
                          className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${ACTIVITY_CATEGORY_CLASSES[event.event_type] ?? "bg-surface-2 text-ink-2"}`}
                        >
                          {ACTIVITY_ICON[event.event_type] ?? <InboxIcon />}
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-ink">{event.title}</p>
                          {activityDescription(event) && (
                            <p className="mt-0.5 line-clamp-2 text-xs text-ink-3">
                              {activityDescription(event)}
                            </p>
                          )}
                        </div>
                        <div className="flex shrink-0 flex-col items-end gap-1.5">
                          <span className="text-[11px] text-ink-3">{relativeTime(event.created_at)}</span>
                          {statusKey && <StatusBadge status={statusKey} />}
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Card>

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
              {recentRunsQuery.isError && (
                <p className="m-5 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                  Could not load recent suite runs.
                </p>
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
                            <code className="rounded bg-surface-2 px-1.5 py-0.5 font-mono text-xs text-ink-2">
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
                {performanceQuery.isError && (
                  <p className="mt-3 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                    Could not load performance data.
                  </p>
                )}
                {performanceQuery.data && performanceQuery.data.points.length === 0 && (
                  <div className="mt-3">
                    <EmptyState
                      icon={<InboxIcon />}
                      title="No completed runs yet"
                      description="This chart fills in as suite runs complete — no data is ever invented here."
                    />
                  </div>
                )}
                {performanceQuery.data && performanceQuery.data.points.length > 0 && (
                  <div className="relative mt-4 flex h-32 items-end gap-1.5">
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

          {/* ---- Right rail: Needs Attention, System Health, promo ---- */}
          <div className="flex flex-col gap-6">
            <Card elevation="raised" padded={false} className="overflow-hidden">
              <div className="flex items-center justify-between border-b border-line px-5 py-4">
                <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
                  Needs Attention
                  {attention.length > 0 && (
                    <span className="flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-accent-ink tabular-nums">
                      {attention.length}
                    </span>
                  )}
                </h2>
                <Link
                  href="/approvals"
                  className="flex items-center gap-1 text-xs font-medium text-accent no-underline hover:text-accent-hover"
                >
                  View all <ArrowRightIcon />
                </Link>
              </div>
              {attentionLoading ? (
                <div className="flex flex-col gap-2 p-5">
                  <Skeleton className="h-10" />
                  <Skeleton className="h-10" />
                </div>
              ) : attention.length === 0 ? (
                <div className="flex items-center gap-2 px-5 py-6 text-sm text-ink-3">
                  <span className="h-1.5 w-1.5 rounded-full bg-success" aria-hidden="true" />
                  Nothing needs attention.
                </div>
              ) : (
                <ul className="divide-y divide-line">
                  {attention.map((item) => (
                    <li key={item.href}>
                      <Link
                        href={item.href}
                        className="flex items-center gap-3 px-5 py-3.5 no-underline transition-colors duration-150 hover:bg-surface"
                      >
                        <span
                          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${TONE_CHIP_CLASSES[STATUS_META[item.status].tone]}`}
                        >
                          <item.icon />
                        </span>
                        <span className="min-w-0 flex-1">
                          <span className="block text-sm font-medium text-ink">
                            {item.count} {item.label}
                          </span>
                        </span>
                        <StatusBadge status={item.status} className="shrink-0" />
                        <ArrowRightIcon className="shrink-0 text-ink-3" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <SystemHealthPanel
              statsOk={statsQuery.isSuccess}
              statsLoading={statsQuery.isLoading}
              statsError={statsQuery.isError}
              verdictOk={verdictQuery.isSuccess}
              verdictLoading={verdictQuery.isLoading}
              verdictError={verdictQuery.isError}
            />

            <PromoCard />
          </div>
        </div>
        </div>
      </div>
    </AppShell>
  );
}
