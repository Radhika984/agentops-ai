import { Card } from "./Card";
import type { Tone } from "./Badge";

// Extracted verbatim from release/page.tsx and regression/page.tsx, which
// each defined an identical copy of this component — a real duplication,
// not a stylistic choice. Every stat-grid page (Release Gate, Regression,
// and any future one) should import this instead of redefining it.
const METRIC_VALUE_TONE: Record<Tone, string> = {
  neutral: "text-ink",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  accent: "text-accent",
};

export function MetricCard({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: Tone;
}) {
  return (
    <Card elevation="raised">
      <p className="text-xs font-medium tracking-wide text-ink-3 uppercase">{label}</p>
      <p className={`mt-2 text-2xl font-bold tracking-tight ${METRIC_VALUE_TONE[tone]}`}>{value}</p>
    </Card>
  );
}
