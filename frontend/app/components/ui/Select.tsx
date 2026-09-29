import type { ReactNode, SelectHTMLAttributes } from "react";

// Matches Input.tsx's inputClasses exactly (see that file's comment on
// why backdrop-blur-md is here — the light theme's bg-surface is opaque
// so it's inert there, the dark .app-canvas theme's is translucent).
const selectClasses =
  "w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink backdrop-blur-md transition-all duration-150 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/15 disabled:opacity-50";

interface SelectFieldProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: ReactNode;
}

/** Label + native <select> pair, matching Input.tsx's Field styling
 * exactly (same border/background/focus-ring treatment) — the smallest
 * addition needed since no select-style component existed yet. */
export function SelectField({ label, id, className = "", children, ...props }: SelectFieldProps) {
  return (
    <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2" htmlFor={id}>
      {label}
      <select id={id} className={`${selectClasses} ${className}`} {...props}>
        {children}
      </select>
    </label>
  );
}
