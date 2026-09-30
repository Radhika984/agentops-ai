"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "./ui/Badge";
import { Card } from "./ui/Card";
import { EmptyState } from "./ui/EmptyState";
import { Skeleton } from "./ui/Skeleton";
import { ApiError, AUTOFIX_OPTION_LABEL, listActivity, type ActivityEventRead } from "../lib/api";

function readString(metadata: Record<string, unknown>, key: string): string | null {
  const value = metadata[key];
  return typeof value === "string" ? value : null;
}

/** A real, metadata-derived status chip for the two event types that
 * carry one (backend/app/services/release_gate_service.py's
 * `{"decision", "hard_gate_passed"}` and autofix_service.py's
 * `{"option", ...}` — see those call sites for the exact shape). Returns
 * null — no chip, just the plain title/description row below — for any
 * event whose metadata doesn't actually contain a recognized field,
 * rather than guessing. */
export function eventBadge(event: ActivityEventRead) {
  if (event.event_type === "release_gate_evaluated") {
    const decision = readString(event.event_metadata, "decision");
    if (decision === "pass") return <Badge tone="success">PASS</Badge>;
    if (decision === "hold") return <Badge tone="danger">HOLD</Badge>;
    return null;
  }
  if (event.event_type === "autofix_proposed") {
    const option = readString(event.event_metadata, "option");
    if (!option) return null;
    // approval_id present ⇒ requires human approval (options 1–3);
    // absent ⇒ owner_suggestion, recorded with no approval needed.
    const requiresApproval = readString(event.event_metadata, "approval_id") !== null;
    return (
      <Badge tone={requiresApproval ? "warning" : "neutral"}>
        {AUTOFIX_OPTION_LABEL[option as keyof typeof AUTOFIX_OPTION_LABEL] ?? option}
      </Badge>
    );
  }
  return null;
}

/** Shared list for the "Release Gate" and "AutoFix" nav pages — both are
 * a filtered view of the exact same real activity log (GET
 * /api/v1/activity?event_type=...) the Home dashboard's Recent Activity
 * widget reads from, not a second data source. */
export function ActivityList({
  eventType,
  emptyIcon,
  emptyTitle,
  emptyDescription,
}: {
  eventType: string;
  emptyIcon: React.ReactNode;
  emptyTitle: string;
  emptyDescription: string;
}) {
  const activityQuery = useQuery({
    queryKey: ["activity", eventType],
    queryFn: () => listActivity(50, eventType),
  });

  return (
    <Card elevation="raised" padded={false} className="mt-7 overflow-hidden">
      {activityQuery.isLoading && (
        <div className="flex flex-col gap-2 p-5">
          <Skeleton className="h-16" />
          <Skeleton className="h-16" />
        </div>
      )}

      {activityQuery.isError && (
        <p className="m-5 rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
          {activityQuery.error instanceof ApiError
            ? activityQuery.error.message
            : "Could not load activity."}
        </p>
      )}

      {activityQuery.data && activityQuery.data.length === 0 && (
        <div className="p-5">
          <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />
        </div>
      )}

      {activityQuery.data && activityQuery.data.length > 0 && (
        <ul className="flex flex-col divide-y divide-line">
          {activityQuery.data.map((event) => {
            const badge = eventBadge(event);
            return (
              <li key={event.id} className="px-5 py-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-2">
                    {badge}
                    <p className="truncate text-sm font-medium text-ink">{event.title}</p>
                  </div>
                  <span className="shrink-0 text-xs text-ink-3">
                    {new Date(event.created_at).toLocaleString()}
                  </span>
                </div>
                {event.description && (
                  <p className="mt-1 text-xs text-ink-3">{event.description}</p>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
