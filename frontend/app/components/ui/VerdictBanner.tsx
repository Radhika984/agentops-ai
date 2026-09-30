import type { ReactNode } from "react";
import type { Tone } from "./Badge";

const TONE_CLASSES: Record<Tone, string> = {
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  accent: "bg-accent-soft text-accent",
  neutral: "bg-surface-2 text-ink-2",
};

/** The app's one "loud moment" component — a large PASS/FAIL/HOLD
 * banner for the single most important decision on a page (can this be
 * released, did this run pass, did this result pass). Generalizes
 * RunAgentPanel's original ReleaseVerdict into a shared primitive so
 * every verdict-driven page uses the same dominant treatment instead of
 * a plain Badge. `reason` is the real "why" line already available on
 * every page that renders this — never invented copy. */
export function VerdictBanner({
  tone,
  icon,
  headline,
  reason,
  className = "",
}: {
  tone: Tone;
  icon: ReactNode;
  headline: string;
  reason?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`animate-fade-in rounded-lg px-4 py-3.5 ${TONE_CLASSES[tone]} ${className}`}>
      <div className="flex items-center gap-2.5 text-base font-semibold">
        {icon}
        {headline}
      </div>
      {reason && <div className="mt-1.5 text-sm font-normal opacity-90">{reason}</div>}
    </div>
  );
}
