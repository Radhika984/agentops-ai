import type { Tone } from "./Badge";
import { StatusDot } from "./Status";

export interface FlowStep {
  label: string;
  tone: Tone;
  pulse?: boolean;
}

/** "AI proposes, humans control" made visible as a real sequence, not
 * just a status word. Generalized from Approvals' original ApprovalFlow
 * — every step passed in must already be derived from real fields
 * (approval status, AutoFix reverification, regression-candidate
 * status); this component only renders whatever sequence the caller
 * already knows to be true, it never invents a stage. */
export function FlowSteps({ steps }: { steps: FlowStep[] }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {steps.map((step, i) => (
        <span key={i} className="flex items-center gap-1.5">
          {i > 0 && <span className="h-px w-3 bg-line-strong" aria-hidden="true" />}
          <StatusDot tone={step.tone} pulse={step.pulse} />
          <span className={`text-[11px] ${step.pulse ? "font-medium text-ink" : "text-ink-3"}`}>
            {step.label}
          </span>
        </span>
      ))}
    </div>
  );
}
