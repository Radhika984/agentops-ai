import type { ReactNode } from "react";
import { ChevronDownIcon } from "./icons";

/** The app's one canonical raw-data block — used everywhere real,
 * unmodified backend JSON (input/output/schema/metadata/diffs) is shown
 * verbatim. `value` is JSON.stringify'd unless it's already a string. */
export function CodeBlock({ value, className = "" }: { value: unknown; className?: string }) {
  const text = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <pre
      className={`text-data overflow-x-auto rounded bg-surface-2 px-2 py-1.5 font-mono whitespace-pre-wrap ${className}`}
    >
      {text}
    </pre>
  );
}

/** A `CodeBlock` with its own uppercase label above it — the
 * "Input"/"Output"/"Actual output" idiom repeated throughout the app. */
export function LabeledCodeBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <p className="text-section-title">{label}</p>
      <CodeBlock value={value} className="mt-1" />
    </div>
  );
}

/** The app's one canonical expand/collapse idiom, extracted from the 7
 * places that previously hand-rolled the same <details>/<summary>
 * markup (RunAgentPanel's ToolCallRow, test-suite/result/execution
 * detail, regression diffs, test-invoke, approvals) — one place to fix
 * or tweak instead of drifting copies.
 *
 * `variant="link"`: the plain text-link disclosure used for "View
 * details" / "View diff details" / "Argument constraints (N)".
 * `variant="row"`: the bordered, chevron-led row used for an
 * inspectable list item (a tool call, an execution) — `meta` renders
 * trailing/right-aligned in the summary (a status Badge, a duration). */
export function Disclosure({
  summary,
  meta,
  children,
  variant = "link",
}: {
  summary: ReactNode;
  meta?: ReactNode;
  children: ReactNode;
  variant?: "link" | "row";
}) {
  if (variant === "row") {
    return (
      <details className="group rounded-md border border-line bg-surface">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-2.5 py-2 text-xs [&::-webkit-details-marker]:hidden">
          <span className="flex min-w-0 items-center gap-2">
            <ChevronDownIcon className="shrink-0 text-ink-3 transition-transform duration-150 group-open:rotate-180" />
            <span className="truncate">{summary}</span>
          </span>
          {meta && <span className="flex shrink-0 items-center gap-2">{meta}</span>}
        </summary>
        <div className="flex flex-col gap-2 border-t border-line px-2.5 py-2.5 text-xs">{children}</div>
      </details>
    );
  }

  return (
    <details className="group">
      <summary className="cursor-pointer list-none text-xs font-medium text-accent [&::-webkit-details-marker]:hidden">
        {summary}
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}
