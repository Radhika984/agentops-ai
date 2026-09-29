import type { ReactNode } from "react";
import { InboxIcon } from "./icons";

export function EmptyState({
  title,
  description,
  action,
  icon,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-line-strong px-6 py-12 text-center">
      <span className="flex h-11 w-11 items-center justify-center rounded-full bg-surface-2 text-ink-3">
        {icon ?? <InboxIcon />}
      </span>
      <div>
        <p className="text-sm font-medium text-ink">{title}</p>
        {description && <p className="mt-1 max-w-sm text-xs text-ink-3">{description}</p>}
      </div>
      {action && <div className="mt-1">{action}</div>}
    </div>
  );
}
