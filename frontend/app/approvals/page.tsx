"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../components/AppShell";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { LabeledCodeBlock } from "../components/ui/CodeDisclosure";
import { EmptyState } from "../components/ui/EmptyState";
import { FlowSteps, type FlowStep } from "../components/ui/FlowSteps";
import { TextInput } from "../components/ui/Input";
import { PageHeader } from "../components/ui/PageHeader";
import { Skeleton } from "../components/ui/Skeleton";
import { ApprovalsIcon, CheckIcon, CloseIcon } from "../components/ui/icons";
import {
  ApiError,
  AUTOFIX_OPTION_LABEL,
  clearToken,
  decideApproval,
  listApprovals,
  type ApprovalRead,
  type AutoFixApprovalPayload,
} from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

const NODE_LABEL: Record<string, string> = {
  auto_fix: "Auto Fix",
  release_decision: "Release decision",
};

// backend/app/services/autofix_service.py only ever writes this JSON
// shape into `reason` for a node="auto_fix" row — parsed defensively;
// any parse failure or a non-autofix node just falls back to plain text.
function parseAutoFixPayload(approval: ApprovalRead): AutoFixApprovalPayload | null {
  if (approval.node !== "auto_fix" || !approval.reason) return null;
  try {
    const parsed = JSON.parse(approval.reason);
    return parsed && parsed.autofix === true ? (parsed as AutoFixApprovalPayload) : null;
  } catch {
    return null;
  }
}

function formatValue(value: unknown): string {
  return value === undefined ? "—" : JSON.stringify(value, null, 2);
}

/** The real originator of a proposal — never a fabricated "requester"
 * field (ApprovalRead has none; both node types are system-raised, not
 * submitted by a person). AutoFix is explicitly AI-generated; a
 * release_decision is the deterministic release-gate pipeline itself —
 * stated plainly rather than invented as if a person proposed it. */
function proposedBy(node: string): string {
  return node === "auto_fix" ? "AgentOps AutoFix (automatic)" : "Release Gate (automatic)";
}

/** "AI proposes, humans control" made visible as a real sequence, not
 * just a status word — every step here is derived from fields the
 * approval/AutoFix payload already has (never a fabricated stage). A
 * pending row shows exactly two steps (Proposed → Pending review, the
 * second pulsing); a decided row shows the real outcome; an AutoFix row
 * whose proposal was actually re-verified (backend/app/api/v1/autofix.py
 * only sets this once a follow-up SuiteRun has actually run) appends
 * that as a final, real step. */
function approvalFlowSteps(approval: ApprovalRead, autofix: AutoFixApprovalPayload | null): FlowStep[] {
  const steps: FlowStep[] = [{ label: "Proposed", tone: "neutral" }];
  if (approval.status === "pending") {
    steps.push({ label: "Pending review", tone: "warning", pulse: true });
  } else {
    steps.push({
      label: approval.status === "approved" ? "Approved" : "Rejected",
      tone: approval.status === "approved" ? "success" : "danger",
    });
  }
  if (autofix?.reverification) {
    steps.push({
      label: autofix.reverification.resolved ? "Re-verified — resolved" : "Re-verified — not resolved",
      tone: autofix.reverification.resolved ? "success" : "warning",
    });
  }
  return steps;
}

function ApprovalRow({ approval }: { approval: ApprovalRead }) {
  const [reason, setReason] = useState("");
  const queryClient = useQueryClient();
  const isPending = approval.status === "pending";

  const decideMutation = useMutation({
    mutationFn: (approved: boolean) => decideApproval(approval.id, approved, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["approvals"] });
    },
  });

  // Never assumes run_id is set — a SuiteRun-scoped approval (Phase 18
  // release_decision / Phase 19 auto_fix) has run_id=null and
  // suite_run_id set instead (exactly one of the two, per the backend's
  // own CHECK constraint). No link is constructed from suite_run_id
  // alone: reaching the real SuiteRun route needs its agentId/suiteId
  // too, which this row doesn't have without an extra lookup — so the
  // id is shown as plain text, the same treatment run_id already got.
  const parentLabel = approval.run_id
    ? `run ${approval.run_id.slice(0, 8)}`
    : approval.suite_run_id
      ? `suite run ${approval.suite_run_id.slice(0, 8)}`
      : "—";

  const autofix = parseAutoFixPayload(approval);
  const flowSteps = approvalFlowSteps(approval, autofix);
  const scope = autofix ? (AUTOFIX_OPTION_LABEL[autofix.action] ?? autofix.action) : NODE_LABEL[approval.node] ?? approval.node;

  return (
    <Card
      elevation="raised"
      className={`relative overflow-hidden transition-shadow duration-150 ${isPending ? "ring-1 ring-warning/25" : ""}`}
    >
      <span
        className={`absolute top-0 left-0 h-full w-1 ${
          approval.status === "approved"
            ? "bg-success"
            : approval.status === "rejected"
              ? "bg-danger"
              : "bg-warning"
        }`}
        aria-hidden="true"
      />

      <div className="flex flex-wrap items-center justify-between gap-2">
        <Badge tone="accent">{NODE_LABEL[approval.node] ?? approval.node}</Badge>
        {isPending && (
          <span className="flex items-center gap-1.5 text-xs font-semibold tracking-wide text-warning uppercase">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-warning" aria-hidden="true" />
            Awaiting your decision
          </span>
        )}
      </div>

      <div className="mt-2">
        <FlowSteps steps={flowSteps} />
      </div>

      {/* WHAT / WHY / WHO / WHEN — governance metadata, each explicitly
          labeled rather than folded into one paragraph, so the reviewer
          can scan a queue of these without reading full sentences. */}
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-4">
        <div>
          <dt className="font-semibold tracking-wide text-ink-3 uppercase">What</dt>
          <dd className="mt-0.5 text-ink-2">
            {scope}
            {autofix?.field && <span className="ml-1 font-mono text-[11px] text-ink-3">{autofix.field}</span>}
          </dd>
        </div>
        <div>
          <dt className="font-semibold tracking-wide text-ink-3 uppercase">Resource</dt>
          <dd className="mt-0.5 font-mono text-[11px] text-ink-2">{parentLabel}</dd>
        </div>
        <div>
          <dt className="font-semibold tracking-wide text-ink-3 uppercase">Proposed by</dt>
          <dd className="mt-0.5 text-ink-2">{proposedBy(approval.node)}</dd>
        </div>
        <div>
          <dt className="font-semibold tracking-wide text-ink-3 uppercase">When</dt>
          <dd className="mt-0.5 text-ink-2">{new Date(approval.requested_at).toLocaleString()}</dd>
        </div>
      </dl>

      {(autofix?.rationale || (!autofix && approval.reason)) && (
        <div className="mt-3">
          <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Why</p>
          <p className="mt-0.5 max-w-xl text-sm whitespace-pre-wrap text-ink-2">
            {autofix ? autofix.rationale : approval.reason}
          </p>
        </div>
      )}

      {autofix && (autofix.current_value !== undefined || autofix.proposed_value !== undefined) && (
        <div className="mt-3 grid grid-cols-1 gap-2 text-xs sm:grid-cols-2">
          <LabeledCodeBlock label="Current" value={formatValue(autofix.current_value)} />
          <LabeledCodeBlock label="Proposed" value={formatValue(autofix.proposed_value)} />
        </div>
      )}

      {autofix?.reverification && (
        <p className="mt-3 rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-xs text-ink-2">
          Re-verification: new suite run{" "}
          <span className="font-mono">{autofix.reverification.suite_run_id.slice(0, 8)}</span> →{" "}
          {autofix.reverification.new_verdict ?? "no result"}
        </p>
      )}

      {/* DECISION — the one governance action this whole card exists
          for, given its own visually distinct zone instead of sitting
          flush with the metadata above it. */}
      {isPending ? (
        <div className="mt-4 flex flex-col gap-2 rounded-md border border-line bg-surface-2 p-3 sm:flex-row sm:items-center">
          <TextInput
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Reason for your decision (optional)"
            className="flex-1"
          />
          <div className="flex gap-2">
            <Button
              variant="success"
              size="sm"
              onClick={() => decideMutation.mutate(true)}
              disabled={decideMutation.isPending}
            >
              <CheckIcon />
              Approve
            </Button>
            <Button
              variant="danger"
              size="sm"
              onClick={() => decideMutation.mutate(false)}
              disabled={decideMutation.isPending}
            >
              <CloseIcon />
              Reject
            </Button>
          </div>
        </div>
      ) : (
        (approval.decided_by || approval.decided_at) && (
          <div className="mt-4 border-t border-line pt-3">
            <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">Decision</p>
            <p className="mt-0.5 text-xs text-ink-2">
              {approval.status === "approved" ? "Approved" : "Rejected"}
              {approval.decided_by ? ` by ${approval.decided_by}` : ""}
              {approval.decided_at ? ` · ${new Date(approval.decided_at).toLocaleString()}` : ""}
            </p>
          </div>
        )
      )}

      {decideMutation.isError && (
        <p className="mt-2 text-xs text-danger">
          {decideMutation.error instanceof ApiError
            ? decideMutation.error.message
            : "Could not record that decision."}
        </p>
      )}
    </Card>
  );
}

type FilterTab = "pending" | "approved" | "rejected" | "all";
const TABS: FilterTab[] = ["pending", "approved", "rejected", "all"];

export default function ApprovalsPage() {
  const router = useRouter();
  const checkedAuth = useRequireAuth();
  const [tab, setTab] = useState<FilterTab>("pending");

  const approvalsQuery = useQuery({
    queryKey: ["approvals", tab],
    queryFn: () => listApprovals(tab === "all" ? undefined : tab),
    enabled: checkedAuth,
  });

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  const count = approvalsQuery.data?.length ?? 0;

  return (
    <AppShell onLogout={handleLogout}>
      <div className="mx-auto w-full max-w-4xl px-4 py-7 md:px-8">
        <PageHeader
          title="Release reviews"
          description="The engineering approval queue — Auto Fix patches and release-gate proposals, from both legacy per-run releases and SuiteRun release reviews. Approve or reject a pending item with an optional reason."
        />

        <div className="mt-5 flex items-center gap-1 border-b border-line">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`relative px-3 py-2 text-sm font-medium capitalize transition-colors duration-150 ${
                tab === t ? "text-ink" : "text-ink-3 hover:text-ink-2"
              }`}
            >
              {t}
              {tab === t && (
                <span className="absolute right-0 -bottom-px left-0 h-0.5 rounded-full bg-accent" />
              )}
            </button>
          ))}
        </div>

        <div className="mt-5 flex flex-col gap-3">
          {approvalsQuery.isLoading && (
            <>
              <Skeleton className="h-24" />
              <Skeleton className="h-24" />
            </>
          )}

          {approvalsQuery.isError && (
            <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
              {approvalsQuery.error instanceof ApiError
                ? approvalsQuery.error.message
                : "Could not load the approval queue."}
            </p>
          )}

          {approvalsQuery.data && count === 0 && (
            <EmptyState
              icon={<ApprovalsIcon />}
              title={tab === "pending" ? "No pending approvals" : `No ${tab === "all" ? "" : tab} approvals`}
              description="Release reviews that need a decision will show up here."
            />
          )}

          {approvalsQuery.data?.map((approval) => (
            <ApprovalRow key={approval.id} approval={approval} />
          ))}
        </div>
      </div>
    </AppShell>
  );
}
