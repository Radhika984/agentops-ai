import type { ReactNode } from "react";

// Extracted verbatim — this exact component was independently defined
// (identically) in 4 files (RunAgentPanel, agents/[agentId]/page,
// test-invoke, execution detail). One real duplication, not a
// stylistic choice; every bordered-panel detail page should import
// this instead of redefining it.
export function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="border-t border-line px-4 py-3.5 first:border-t-0">
      <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">{label}</p>
      <div className="mt-2">{children}</div>
    </div>
  );
}
