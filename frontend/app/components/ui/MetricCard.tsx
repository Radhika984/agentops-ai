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
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: Tone;
}) {
  return (
    <Card elevation="raised">
      <p className="text-metric-label">{label}</p>
      <p className={`text-metric-value mt-2 ${METRIC_VALUE_TONE[tone]}`}>{value}</p>
      {hint && <p className="text-body-muted mt-1">{hint}</p>}
    </Card>
  );
}
