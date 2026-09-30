import type { ReactNode } from "react";

// Extracted from the identical title+description(+action) markup that
// was hand-written at the top of every list/detail page in the app
// (text-3xl font-bold tracking-tight text-ink / mt-1.5 text-sm text-ink-2)
// — a real, repeated pattern, not a speculative abstraction. Formalizes
// the app's "page title" typography tier as one reusable primitive
// instead of a convention every file had to remember to copy correctly.
export function PageHeader({
  title,
  description,
  action,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <h1 className="text-page-title">{title}</h1>
        {description && <p className="text-body mt-1.5 max-w-2xl">{description}</p>}
      </div>
      {action}
    </div>
  );
}
