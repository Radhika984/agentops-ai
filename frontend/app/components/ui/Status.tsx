import type { ReactNode } from "react";
import type { Tone } from "./Badge";
import {
  CheckCircleIcon,
  ClockIcon,
  DashedCircleIcon,
  HalfCircleIcon,
  PauseOctagonIcon,
  ShieldCheckIcon,
  XCircleIcon,
  XSquareIcon,
} from "./icons";

/** The app's one status vocabulary (design brief §"Status language").
 * Every place that shows one of these eight real outcomes — a verdict,
 * a release decision, an approval, an evidence tier — reads its
 * icon/tone/label from here, never re-derives its own color mapping.
 * Each entry pairs a distinct icon SHAPE with a tone and a label, so two
 * statuses are never distinguishable by color alone. Warning (amber) is
 * deliberately never used here — it's reserved for soft/advisory signals
 * (latency, pass rate) that must never look like a release blocker. */
export type StatusKey =
  | "PASS"
  | "FAIL"
  | "HOLD"
  | "INCONCLUSIVE"
  | "INSUFFICIENT_EVIDENCE"
  | "PENDING"
  | "APPROVED"
  | "REJECTED";

export interface StatusMetaEntry {
  tone: Tone;
  icon: (props: { className?: string }) => ReactNode;
  label: string;
}

export const STATUS_META: Record<StatusKey, StatusMetaEntry> = {
  PASS: { tone: "success", icon: CheckCircleIcon, label: "PASS" },
  FAIL: { tone: "danger", icon: XCircleIcon, label: "FAIL" },
  // HOLD is a release-blocking outcome, same severity as FAIL — it stays
  // on danger, never amber, and is told apart from FAIL only by its
  // distinct octagon/pause shape and its own label, never by color alone.
  HOLD: { tone: "danger", icon: PauseOctagonIcon, label: "HOLD" },
  INCONCLUSIVE: { tone: "neutral", icon: HalfCircleIcon, label: "INCONCLUSIVE" },
  INSUFFICIENT_EVIDENCE: {
    tone: "neutral",
    icon: DashedCircleIcon,
    label: "INSUFFICIENT EVIDENCE",
  },
  PENDING: { tone: "accent", icon: ClockIcon, label: "PENDING" },
  APPROVED: { tone: "success", icon: ShieldCheckIcon, label: "APPROVED" },
  REJECTED: { tone: "neutral", icon: XSquareIcon, label: "REJECTED" },
};

const dotColor: Record<Tone, string> = {
  neutral: "bg-ink-3",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  accent: "bg-accent",
};

const textColor: Record<Tone, string> = {
  neutral: "text-ink-2",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  accent: "text-accent",
};

/** A small solid dot indicator — optionally pulsing for an in-progress
 * state (e.g. a run that's still executing). Used on its own or inside
 * StatusLabel below. */
export function StatusDot({ tone = "neutral", pulse = false }: { tone?: Tone; pulse?: boolean }) {
  return (
    <span className="relative inline-flex h-1.5 w-1.5 shrink-0">
      {pulse && (
        <span
          className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${dotColor[tone]}`}
        />
      )}
      <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${dotColor[tone]}`} />
    </span>
  );
}

/** A dot + label pair, restrained per the "small indicator + clear label"
 * pattern — never a large colorful pill for a status by itself. */
export function StatusLabel({
  tone = "neutral",
  pulse = false,
  children,
}: {
  tone?: Tone;
  pulse?: boolean;
  children: ReactNode;
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 text-sm font-medium ${textColor[tone]}`}>
      <StatusDot tone={tone} pulse={pulse} />
      {children}
    </span>
  );
}

// A "soft chip" tone→class pairing (soft background + matching text) —
// shared by StatusBadge below and by any other chip (e.g. Home's Recent
// Activity icon chips) that needs to color itself by real tone rather
// than a decorative, unrelated hue.
export const TONE_CHIP_CLASSES: Record<Tone, string> = {
  neutral: "bg-surface-2 text-ink-2",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  accent: "bg-accent-soft text-accent",
};

/** The compact, table/list-row rendering of the STATUS_META vocabulary —
 * icon shape + label together, so status is never conveyed by color
 * alone. Use this (not a plain `Badge`) anywhere one of the eight real
 * statuses above is shown; `Badge` remains for everything else (counts,
 * categories, free-text tags) that isn't part of this vocabulary. */
export function StatusBadge({ status, className = "" }: { status: StatusKey; className?: string }) {
  const meta = STATUS_META[status];
  const Icon = meta.icon;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-control px-1.5 py-0.5 text-xs font-medium whitespace-nowrap ${TONE_CHIP_CLASSES[meta.tone]} ${className}`}
    >
      <Icon className="shrink-0" />
      {meta.label}
    </span>
  );
}
