import type { ReactNode } from "react";
import Link from "next/link";
import { Card } from "./Card";
import { ArrowRightIcon } from "./icons";
import { Skeleton } from "./Skeleton";

export type StatTone = "orange" | "teal" | "purple" | "pink";

// Purely categorical color-coding — "which stat card is this", never a
// status/semantic meaning (PASS/FAIL/INCONCLUSIVE stay on
// success/warning/danger everywhere else in the app). Shared across
// every page that uses StatCard (Home, Cost, ...) and by
// Home's Recent Activity icon coloring (see activityTone in
// app/home/page.tsx), so every "which category is this" accent in the
// app draws from the same four tones.
export const STAT_TONE_CLASSES: Record<
  StatTone,
  { chip: string; glow: string; wave: string; wash: string }
> = {
  orange: {
    chip: "bg-accent-soft text-accent ring-accent/15",
    glow: "bg-accent/20",
    wave: "var(--accent)",
    wash: "var(--accent)",
  },
  teal: {
    chip: "bg-stat-teal-soft text-stat-teal ring-stat-teal/15",
    glow: "bg-stat-teal/20",
    wave: "var(--stat-teal)",
    wash: "var(--stat-teal)",
  },
  purple: {
    chip: "bg-stat-purple-soft text-stat-purple ring-stat-purple/15",
    glow: "bg-stat-purple/20",
    wave: "var(--stat-purple)",
    wash: "var(--stat-purple)",
  },
  pink: {
    chip: "bg-stat-pink-soft text-stat-pink ring-stat-pink/15",
    glow: "bg-stat-pink/20",
    wave: "var(--stat-pink)",
    wash: "var(--stat-pink)",
  },
};

/** ONE shared decorative curve, reused identically by every StatCard —
 * only the stroke color (toneClasses.wave) differs between instances.
 * Giving each card its own path shape previously read as inconsistent,
 * unaligned decorations rather than "one component, four accent
 * colors." Kept as a single module-level constant so there's no code
 * path that could let instances drift apart again. */
const STAT_WAVE_PATH = "M4 52 C 20 44, 28 60, 44 46 C 58 34, 66 52, 82 28 C 90 18, 96 22, 108 8";

/**
 * The one shared "KPI tile" component used across every dashboard page
 * (Home's four top-line stats, Cost's three metric cards, and any future
 * page that shows a single real number) — icon chip, optional real
 * navigation arrow, label, and value, always in the same fixed-height,
 * two-row layout regardless of label length. `href` is optional and
 * deliberately controls whether an arrow is shown at all: a card with no
 * real drill-down destination gets no arrow, since a decorative arrow
 * that leads nowhere is exactly the "button that does nothing" this app
 * avoids everywhere else.
 */
export function StatCard({
  icon,
  label,
  value,
  hint,
  loading,
  isError,
  index = 0,
  tone = "orange",
  href,
}: {
  icon: ReactNode;
  label: string;
  value: number | string | undefined;
  /** Optional real, already-computed context line under the value (e.g.
   * "10% of all calls", "Free Tier — not billed") — never invented, only
   * ever the caller's own already-fetched data. */
  hint?: string;
  loading: boolean;
  isError?: boolean;
  index?: number;
  tone?: StatTone;
  href?: string;
}) {
  const toneClasses = STAT_TONE_CLASSES[tone];

  const inner = (
    // atmosphere={false}: this card already carries its own bespoke
    // per-tone corner wash below — Card's default generic corner glow
    // (see globals.css's .card-depth) would just stack a second, duller
    // glow in the exact same corner.
    <Card
      elevation="raised"
      atmosphere={false}
      className={`relative flex h-40 flex-col justify-between overflow-hidden ${href ? "glow-hover" : ""}`}
    >
      <span
        className={`pointer-events-none absolute -top-6 -left-6 h-20 w-20 rounded-full blur-2xl ${toneClasses.glow}`}
        aria-hidden="true"
      />
      {/* A second, distinct atmosphere layer from the icon glow above —
          a wide, actually-visible tinted radial wash seated in the
          card's own bottom-right corner (where the light trail below
          also lives), giving the card a "lit from one corner" glass
          depth rather than a flat tinted rectangle. Identical geometry
          on every card — only toneClasses.wash (the color) differs. */}
      <div
        className="pointer-events-none absolute inset-0 rounded-lg opacity-[0.28]"
        style={{
          background: `radial-gradient(ellipse 75% 65% at 100% 100%, ${toneClasses.wash} 0%, transparent 68%)`,
        }}
        aria-hidden="true"
      />
      {/* Purely decorative — NOT a sparkline/chart line. Every StatCard
          uses the exact same STAT_WAVE_PATH, same box, same stroke
          widths, same blur, same opacity — one reusable decoration
          repeated across cards with only its color changing. Two layers
          of the same curve: a blurred, wide-stroke "glow" copy
          underneath for soft ambient light, and a crisp, thin,
          gradient-faded stroke on top for the actual visible line — the
          main stroke itself stays unblurred so it reads as "a clean line
          with a glow behind it," not one blurry smear. Clipped by the
          card's own overflow-hidden; no axis, no markers. */}
      <svg
        className="pointer-events-none absolute right-0 bottom-0 h-16 w-28 opacity-45 blur-md"
        viewBox="0 0 112 64"
        fill="none"
        aria-hidden="true"
      >
        <path d={STAT_WAVE_PATH} stroke={toneClasses.wave} strokeWidth="5" strokeLinecap="round" />
      </svg>
      <svg
        className="pointer-events-none absolute right-0 bottom-0 h-16 w-28 opacity-90"
        viewBox="0 0 112 64"
        fill="none"
        aria-hidden="true"
      >
        <defs>
          <linearGradient id={`wave-fade-${tone}`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor={toneClasses.wave} stopOpacity="0" />
            <stop offset="45%" stopColor={toneClasses.wave} stopOpacity="0.95" />
            <stop offset="100%" stopColor={toneClasses.wave} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path
          d={STAT_WAVE_PATH}
          stroke={`url(#wave-fade-${tone})`}
          strokeWidth="2"
          strokeLinecap="round"
        />
      </svg>

      {/* Row 1: icon chip (left) + arrow (right, only when href is
          given) — fixed row, nothing in it can wrap, so its height (and
          therefore the icon's and arrow's vertical position) is
          identical on every card. */}
      <div className="relative flex items-start justify-between">
        <span
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ring-1 ${toneClasses.chip}`}
        >
          {icon}
        </span>
        {href && (
          <ArrowRightIcon className="mt-1 shrink-0 text-ink-3 opacity-60 transition-all duration-200 group-hover:translate-x-0.5 group-hover:text-ink group-hover:opacity-100" />
        )}
      </div>

      {/* Row 2: label + value, pinned to the card's bottom edge. The
          label gets a reserved min-h-9 (fits two lines) regardless of
          how many lines THIS card's own label actually takes, so the
          value directly below it always starts at the same vertical
          position across every card using this component. */}
      <div className="relative">
        <p className="min-h-9 text-xs leading-tight font-medium tracking-wide text-ink-3 uppercase">
          {label}
        </p>
        {loading ? (
          <Skeleton className="mt-1 h-7 w-12" />
        ) : (
          <>
            <p className="mt-1 text-2xl font-bold text-ink tabular-nums">
              {isError ? "—" : (value ?? "—")}
            </p>
            {hint && !isError && <p className="mt-0.5 truncate text-[11px] text-ink-3">{hint}</p>}
          </>
        )}
      </div>
    </Card>
  );

  if (!href) {
    return (
      <div className="animate-fade-in-up" style={{ animationDelay: `${index * 60}ms` }}>
        {inner}
      </div>
    );
  }

  return (
    <Link
      href={href}
      className="group animate-fade-in-up block rounded-lg no-underline focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/25"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      {inner}
    </Link>
  );
}
