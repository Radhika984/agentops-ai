import type { ReactNode } from "react";
import type { Tone } from "./Badge";

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
