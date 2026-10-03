import type { ReactNode } from "react";
import Link from "next/link";
import { Card } from "./Card";
import { ArrowRightIcon } from "./icons";
import { Skeleton } from "./Skeleton";

// Phase 1 UI-elevation audit: this used to carry four categorical hues
// (orange/teal/purple/pink) purely to color-code "which stat is this" —
// exactly the decorative, non-status color-coding the design brief asks
// to remove ("restraint is the point"). A KPI count (Total projects,
// Agents, ...) has no status meaning, so it stays neutral; `accent` is
// available for at most one genuinely emphasized tile on a page, never
// applied by rotation/index the way the old tones were.
export type StatTone = "neutral" | "accent";

const STAT_TONE_CLASSES: Record<StatTone, { chip: string }> = {
  neutral: { chip: "bg-surface-2 text-ink-2 ring-line-strong" },
  accent: { chip: "bg-accent-soft text-accent ring-accent/15" },
};

/**
 * The one shared "KPI tile" component used across every dashboard page
 * (Home's top-line stats, Cost's metric cards, and any future page that
 * shows a single real number) — icon chip, optional real navigation
 * arrow, label, and value, always in the same fixed-height, two-row
 * layout regardless of label length. `href` is optional and deliberately
 * controls whether an arrow is shown at all: a card with no real
 * drill-down destination gets no arrow, since a decorative arrow that
 * leads nowhere is exactly the "button that does nothing" this app
 * avoids everywhere else. Deliberately flat/quiet (no colored glow, no
 * decorative wave) — a KPI row is a data-dense summary, not a hero.
 */
export function StatCard({
  icon,
  label,
  value,
  hint,
  loading,
  isError,
  index = 0,
  tone = "neutral",
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
    <Card
      elevation="raised"
      className={`relative flex h-40 flex-col justify-between ${href ? "glow-hover" : ""}`}
    >
      <div className="flex items-start justify-between">
        <span
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-control ring-1 ${toneClasses.chip}`}
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
      <div>
        <p className="min-h-9 text-xs leading-tight font-medium tracking-wide text-ink-3 uppercase">
          {label}
        </p>
        {loading ? (
          <Skeleton className="mt-1 h-7 w-12" />
        ) : (
          <>
            <p className="text-metric-value mt-1 text-ink">{isError ? "—" : (value ?? "—")}</p>
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
      className="group animate-fade-in-up block rounded-surface no-underline focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/25"
      style={{ animationDelay: `${index * 60}ms` }}
    >
      {inner}
    </Link>
  );
}
