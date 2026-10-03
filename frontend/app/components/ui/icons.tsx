import type { SVGProps } from "react";

// Small, hand-authored, stroke-based icon set — no icon library dependency.
// Consistent 18x18 viewBox, 1.6 stroke width, currentColor throughout.

type IconProps = SVGProps<SVGSVGElement>;

const base = {
  width: 16,
  height: 16,
  viewBox: "0 0 18 18",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.6,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

/** Restrained geometric brand mark for "AgentOps AI" — three connected
 * nodes inside a rounded square, evoking agent orchestration without any
 * literal robot/brain imagery. */
export function BrandMark(props: IconProps) {
  return (
    <svg {...base} width={20} height={20} {...props}>
      <rect x="1" y="1" width="16" height="16" rx="4" stroke="currentColor" />
      <circle cx="6" cy="6.2" r="1.15" fill="currentColor" stroke="none" />
      <circle cx="12.4" cy="6.2" r="1.15" fill="currentColor" stroke="none" />
      <circle cx="9.2" cy="12.2" r="1.15" fill="currentColor" stroke="none" />
      <path d="M6.9 7.1 8.4 11.2M11.5 7.1 10 11.2M7.1 6.2h4.2" />
    </svg>
  );
}

export function ProjectsIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <rect x="2" y="4" width="14" height="11" rx="1.5" />
      <path d="M2 7.2h14" />
      <path d="M6 2v3.2M12 2v3.2" />
    </svg>
  );
}

export function CostIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M3 15V9M8 15V4M13 15v-6.5" />
      <path d="M2 15.5h14" />
    </svg>
  );
}

export function ApprovalsIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M9 2 3 4.4v4.2c0 3.6 2.4 6.4 6 7.4 3.6-1 6-3.8 6-7.4V4.4Z" />
      <path d="M6.4 9 8.3 10.9 11.8 7.2" />
    </svg>
  );
}

export function LogoutIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M7 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h3" />
      <path d="M12 12.5 15.5 9 12 5.5" />
      <path d="M15.3 9H6.8" />
    </svg>
  );
}

export function MenuIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M2.5 5h13M2.5 9h13M2.5 13h13" />
    </svg>
  );
}

export function CloseIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M4.5 4.5 13.5 13.5M13.5 4.5 4.5 13.5" />
    </svg>
  );
}

export function ChevronLeftIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M11 3.5 5.5 9l5.5 5.5" />
    </svg>
  );
}

export function SendIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M2.5 9 15.5 3 11 15.5 8.3 10.2 2.5 9Z" />
      <path d="M8.3 10.2 12.2 6.3" />
    </svg>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M3.5 9.5 7 13l7.5-8.5" />
    </svg>
  );
}

/** Generic small technical mark for empty states — an open tray, not a
 * literal "nothing here" illustration. */
export function InboxIcon(props: IconProps) {
  return (
    <svg {...base} width={22} height={22} {...props}>
      <path d="M2.5 9 4.8 3.2h8.4L15.5 9" />
      <path d="M2.5 9v5c0 .55.45 1 1 1h11c.55 0 1-.45 1-1V9" />
      <path d="M2.5 9h4l1 2h3l1-2h4" />
    </svg>
  );
}

/** Empty-state mark specific to "no evaluation projects yet" — a goal
 * node flowing into a check, evoking the evaluation pipeline rather than
 * a generic empty folder/inbox. */
export function EvaluationMark(props: IconProps) {
  return (
    <svg {...base} width={24} height={24} {...props}>
      <circle cx="4" cy="9" r="2.1" />
      <path d="M6.1 9h4.4" strokeDasharray="1.6 1.8" />
      <rect x="10.5" y="5.3" width="6.2" height="7.4" rx="1.6" />
      <path d="M12.3 9 13.7 10.4 16 7.7" />
    </svg>
  );
}

export function ArrowRightIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M3 9h12M10.5 4.5 15 9l-4.5 4.5" />
    </svg>
  );
}

export function EyeIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M1.5 9S4.2 3.8 9 3.8 16.5 9 16.5 9 13.8 14.2 9 14.2 1.5 9 1.5 9Z" />
      <circle cx="9" cy="9" r="2.3" />
    </svg>
  );
}

export function WarningIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M9 2.3 16 14.5H2Z" />
      <path d="M9 7.3v3.3" />
      <circle cx="9" cy="12.7" r="0.15" fill="currentColor" stroke="currentColor" strokeWidth="1" />
    </svg>
  );
}

export function EyeOffIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M1.5 9S4.2 3.8 9 3.8c1.15 0 2.19.24 3.11.62M16.5 9s-1.1 2.06-3.04 3.4M9 14.2c-2.9 0-5.06-1.63-6.4-3.15" />
      <path d="M7.3 7.3a2.3 2.3 0 0 0 3.4 3.4" />
      <path d="M2.5 2.5l13 13" />
    </svg>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="7.8" cy="7.8" r="5.3" />
      <path d="M11.7 11.7 16 16" />
    </svg>
  );
}

export function ChevronDownIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M4 6.5 9 11.5 14 6.5" />
    </svg>
  );
}

/** Post-release monitoring nav mark — a pulse line, distinct from
 * CostIcon's bar chart, evoking "watching a live signal" rather than a
 * static report. */
export function MonitoringIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M2 9.5h3l1.6-4.3 2.6 8 2-6.6 1.4 2.9H16" />
    </svg>
  );
}

export function ClockIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="9" r="6.5" />
      <path d="M9 5.5V9l2.6 1.6" />
    </svg>
  );
}

/** Status-vocabulary marks (STATUS_META in ui/Status.tsx) — each status
 * gets a distinct OUTER SHAPE (circle / octagon / dashed circle / shield
 * / square), not just a different inner glyph, so two statuses are never
 * distinguishable by color alone. */
export function CheckCircleIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="9" r="6.5" />
      <path d="M6 9.2 8.1 11.3 12.2 6.8" />
    </svg>
  );
}

export function XCircleIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="9" r="6.5" />
      <path d="M6.8 6.8 11.2 11.2M11.2 6.8 6.8 11.2" />
    </svg>
  );
}

/** HOLD — an octagon (the universal "stop and check" shape) with a pause
 * glyph inside, deliberately distinct from FAIL's circle+X in both outer
 * shape and inner mark, never just a different color on the same shape. */
export function PauseOctagonIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M6.2 2.5h5.6L15.5 6.2v5.6L11.8 15.5H6.2L2.5 11.8V6.2Z" />
      <path d="M7.2 6.5v5M10.8 6.5v5" />
    </svg>
  );
}

/** INCONCLUSIVE — a circle bisected by a diameter line ("some evidence
 * either way, no clear verdict"), distinct from the dashed ring used for
 * INSUFFICIENT EVIDENCE ("no usable evidence at all"). */
export function HalfCircleIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="9" r="6.5" />
      <path d="M9 2.5v13" />
    </svg>
  );
}

/** INSUFFICIENT EVIDENCE — a dashed, incomplete ring: there isn't enough
 * signal to draw a solid conclusion, shown structurally rather than only
 * through color. */
export function DashedCircleIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="9" r="6.5" strokeDasharray="2.4 2.6" />
      <circle cx="9" cy="9" r="0.4" fill="currentColor" stroke="none" />
    </svg>
  );
}

/** APPROVED — SafetyIcon's shield outline plus a check, reused
 * deliberately (a human decision that clears something to proceed is the
 * same idea as "safe to proceed"). */
export function ShieldCheckIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M9 2.3 15 4.6v4.2c0 3.6-2.6 6.5-6 7.4-3.4-.9-6-3.8-6-7.4V4.6Z" />
      <path d="M6.2 9 8.1 10.9 11.8 7.2" />
    </svg>
  );
}

/** REJECTED — a square (not a circle) with an X, so it reads as visually
 * distinct from FAIL's circle+X at a glance, not just a color swap. */
export function XSquareIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <rect x="2.3" y="2.3" width="13.4" height="13.4" rx="3" />
      <path d="M6.8 6.8 11.2 11.2M11.2 6.8 6.8 11.2" />
    </svg>
  );
}

/** Evaluation-pipeline stage marks (landing hero + run panel), each a
 * small distinct glyph rather than a single reused dot — Goal, Plan,
 * Tools, Safety, Verify, Release. */
export function GoalIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="9" r="6.3" />
      <circle cx="9" cy="9" r="3.2" />
      <circle cx="9" cy="9" r="0.4" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function PlanIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M3.5 4.5h11M3.5 9h7M3.5 13.5h9" />
      <circle cx="14.7" cy="9" r="1" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function ToolsIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M11.2 6.8a2.6 2.6 0 0 1-3.4 3.4L4 14l-.9-.9L7 9.3A2.6 2.6 0 0 1 10.4 6l-1.6 1.6 1.2 1.2 1.6-1.6Z" />
    </svg>
  );
}

export function SafetyIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M9 2.3 15 4.6v4.2c0 3.6-2.6 6.5-6 7.4-3.4-.9-6-3.8-6-7.4V4.6Z" />
    </svg>
  );
}

export function VerifyIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="9" r="6.5" />
      <path d="M6 9.2 8.1 11.3 12.2 6.8" />
    </svg>
  );
}

/** Agent Registry nav mark — a single agent node inside a rounded frame,
 * distinct from ProjectsIcon's folder shape and BrandMark's multi-node
 * orchestration mark. */
export function AgentIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <rect x="2.3" y="2.3" width="13.4" height="13.4" rx="3" />
      <circle cx="9" cy="7.6" r="2.05" />
      <path d="M5.4 14c.65-1.7 2.05-2.5 3.6-2.5s2.95.8 3.6 2.5" />
    </svg>
  );
}

export function ReleaseIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M9 2.5 9 13" />
      <path d="M5.5 6 9 2.5 12.5 6" />
      <path d="M3.5 12v1.5a1 1 0 0 0 1 1h9a1 1 0 0 0 1-1V12" />
    </svg>
  );
}

/** Home nav mark — a plain roofline, distinct from ProjectsIcon's folder
 * shape and BrandMark's orchestration mark. */
export function HomeIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M2.5 8.5 9 2.8l6.5 5.7" />
      <path d="M4.2 7.2V15h9.6V7.2" />
      <path d="M7 15v-4.5h4V15" />
    </svg>
  );
}

/** Test Suites nav mark — stacked, checked layers (a grouping of cases),
 * distinct from ProjectsIcon's single folder. */
export function TestSuitesIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <rect x="2.5" y="2.5" width="13" height="4.2" rx="1.2" />
      <rect x="2.5" y="8.4" width="13" height="4.2" rx="1.2" />
      <path d="M5.5 4.6 6.4 5.5 8 3.9" />
      <path d="M5.5 10.5 6.4 11.4 8 9.8" />
    </svg>
  );
}

/** Runs nav mark — a play glyph inside a small history/queue frame,
 * distinct from SendIcon's paper-plane and ReleaseIcon's up-arrow. */
export function RunsIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <rect x="2.3" y="2.3" width="13.4" height="13.4" rx="3" />
      <path d="M7.3 6 12 9l-4.7 3Z" />
    </svg>
  );
}

/** RCA nav mark — a magnifying glass over a small fault mark, distinct
 * from SearchIcon's plain lens (that one stays reserved for the global
 * search field). */
export function RCAIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="7.6" cy="7.6" r="5.1" />
      <path d="M11.3 11.3 16 16" />
      <path d="M7.6 5.3v2.6M7.6 9.4v.15" />
    </svg>
  );
}

/** Settings nav mark — a gear, the conventional settings glyph. */
export function SettingsIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="9" r="2.4" />
      <path d="M9 2.6v2M9 13.4v2M15.4 9h-2M4.6 9h-2M13.5 4.5l-1.4 1.4M5.9 12.1l-1.4 1.4M13.5 13.5l-1.4-1.4M5.9 5.9 4.5 4.5" />
    </svg>
  );
}

/** Header notification-bell mark — links to Approvals (the one real
 * "things awaiting you" destination already in the app), badge count is
 * the existing pending-approvals query, never an invented notification
 * feed. */
export function BellIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M5 7.4a4 4 0 0 1 8 0c0 3.1.8 4.2 1.6 5.1H3.4c.8-.9 1.6-2 1.6-5.1Z" />
      <path d="M7.6 14.8a1.6 1.6 0 0 0 2.8 0" />
    </svg>
  );
}

/** Time-of-day greeting marks — one distinct glyph per bucket
 * (morning/afternoon/evening/night), computed client-side only (see
 * home/page.tsx's useTimeOfDay) so the icon and label always match the
 * viewer's own local clock without a server/client hydration mismatch. */
export function SunriseIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M2.5 12h13" />
      <path d="M4.5 12a4.5 4.5 0 0 1 9 0" />
      <path d="M9 3v2.4M3.6 6.2l1.4 1.4M14.4 6.2 13 7.6" />
    </svg>
  );
}

export function SunIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <circle cx="9" cy="9" r="3.2" />
      <path d="M9 2.2v1.9M9 13.9v1.9M2.2 9h1.9M13.9 9h1.9M4.3 4.3l1.4 1.4M12.3 12.3l1.4 1.4M13.7 4.3l-1.4 1.4M5.7 12.3l-1.4 1.4" />
    </svg>
  );
}

export function SunsetIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M2.5 12h13" />
      <path d="M4.5 12a4.5 4.5 0 0 1 9 0" />
      <path d="M9 6.4V3.8M4.9 4.6l1.3 1.3M13.1 4.6l-1.3 1.3" />
      <path d="M3 14.8h12" />
    </svg>
  );
}

export function MoonIcon(props: IconProps) {
  return (
    <svg {...base} {...props}>
      <path d="M14.5 10.8A6 6 0 1 1 7.2 3.5a4.8 4.8 0 0 0 7.3 7.3Z" />
    </svg>
  );
}
