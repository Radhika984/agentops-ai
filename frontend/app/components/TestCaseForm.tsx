"use client";

import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { Button } from "./ui/Button";
import { Field, TextInput } from "./ui/Input";
import {
  ASSERTION_OPS,
  ApiError,
  createTestCase,
  patchTestCase,
  type Assertion,
  type AssertionOp,
  type ExpectedToolCall,
  type TestCaseCreate,
  type TestCasePatch,
  type TestCaseRead,
} from "../lib/api";

const textareaClasses =
  "w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3 transition-colors duration-150 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/10";

const selectClasses =
  "rounded-md border border-line-strong bg-surface px-2 py-2 text-xs text-ink transition-colors duration-150 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/10";

// ---- draft <-> wire-format conversion -----------------------------------
// Assertion/ExpectedToolCall values round-trip through JSON.parse/
// JSON.stringify only — never eval()/Function() — and every value is
// treated purely as data, never executed.

interface AssertionDraft {
  path: string;
  op: AssertionOp;
  value: string;
}

interface ToolCallDraft {
  tool: string;
  orderIndex: string;
  required: boolean;
  argsConstraints: AssertionDraft[];
}

function parseAssertionValue(raw: string): unknown {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  try {
    return JSON.parse(trimmed);
  } catch {
    return raw;
  }
}

function stringifyAssertionValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function draftsToAssertions(drafts: AssertionDraft[]): Assertion[] {
  return drafts
    .filter((d) => d.path.trim() !== "")
    .map((d) => ({
      path: d.path.trim(),
      op: d.op,
      ...(d.op === "exists" ? {} : { value: parseAssertionValue(d.value) }),
    }));
}

function assertionsToDrafts(assertions: Assertion[] | null | undefined): AssertionDraft[] {
  return (assertions ?? []).map((a) => ({
    path: a.path,
    op: a.op,
    value: stringifyAssertionValue(a.value),
  }));
}

function draftsToToolCalls(drafts: ToolCallDraft[]): ExpectedToolCall[] {
  return drafts
    .filter((d) => d.tool.trim() !== "")
    .map((d) => ({
      tool: d.tool.trim(),
      required: d.required,
      order_index: d.orderIndex.trim() !== "" ? Number(d.orderIndex) : null,
      args_constraints: d.argsConstraints.length > 0 ? draftsToAssertions(d.argsConstraints) : null,
    }));
}

function toolCallsToDrafts(calls: ExpectedToolCall[] | null | undefined): ToolCallDraft[] {
  return (calls ?? []).map((c) => ({
    tool: c.tool,
    orderIndex: c.order_index !== null && c.order_index !== undefined ? String(c.order_index) : "",
    required: c.required ?? true,
    argsConstraints: assertionsToDrafts(c.args_constraints),
  }));
}

function linesToArray(text: string): string[] | null {
  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);
  return lines.length > 0 ? lines : null;
}

function arrayToLines(values: string[] | null | undefined): string {
  return values && values.length > 0 ? values.join("\n") : "";
}

interface CaseFormState {
  name: string;
  input: string;
  expectedOutput: string;
  assertions: AssertionDraft[];
  referenceContext: string;
  expectedToolCalls: ToolCallDraft[];
  expectedBehavior: string;
  forbiddenBehavior: string;
  allowedTools: string;
  outputSchema: string;
  latencyThresholdMs: string;
  rubric: string;
  rubricThreshold: string;
  trialCount: string;
  tags: string;
  metadata: string;
}

function emptyFormState(): CaseFormState {
  return {
    name: "",
    input: "{}",
    expectedOutput: "",
    assertions: [],
    referenceContext: "",
    expectedToolCalls: [],
    expectedBehavior: "",
    forbiddenBehavior: "",
    allowedTools: "",
    outputSchema: "",
    latencyThresholdMs: "",
    rubric: "",
    rubricThreshold: "0.7",
    trialCount: "1",
    tags: "",
    metadata: "{}",
  };
}

function toFormState(tc: TestCaseRead): CaseFormState {
  return {
    name: tc.name,
    input: JSON.stringify(tc.input ?? {}, null, 2),
    expectedOutput: tc.expected_output ?? "",
    assertions: assertionsToDrafts(tc.assertions),
    referenceContext: tc.reference_context ?? "",
    expectedToolCalls: toolCallsToDrafts(tc.expected_tool_calls),
    expectedBehavior: arrayToLines(tc.expected_behavior),
    forbiddenBehavior: arrayToLines(tc.forbidden_behavior),
    allowedTools: arrayToLines(tc.allowed_tools),
    outputSchema: tc.output_schema ? JSON.stringify(tc.output_schema, null, 2) : "",
    latencyThresholdMs: tc.latency_threshold_ms !== null ? String(tc.latency_threshold_ms) : "",
    rubric: tc.rubric ?? "",
    rubricThreshold: String(tc.rubric_threshold),
    trialCount: String(tc.trial_count),
    tags: arrayToLines(tc.tags),
    metadata:
      tc.metadata && Object.keys(tc.metadata).length > 0 ? JSON.stringify(tc.metadata, null, 2) : "{}",
  };
}

// Client-side mirror of backend/app/services/test_suite_service.py's
// GROUND_TRUTH_FIELDS rule — used only to steer the UI (disable Save
// early with a clear reason); the backend re-validates independently and
// remains authoritative.
function hasGroundTruth(form: CaseFormState): boolean {
  return (
    form.expectedOutput.trim() !== "" ||
    form.assertions.length > 0 ||
    form.referenceContext.trim() !== "" ||
    form.expectedToolCalls.length > 0 ||
    form.rubric.trim() !== ""
  );
}

function AssertionsEditor({
  assertions,
  onChange,
}: {
  assertions: AssertionDraft[];
  onChange: (next: AssertionDraft[]) => void;
}) {
  function update(i: number, patch: Partial<AssertionDraft>) {
    onChange(assertions.map((a, idx) => (idx === i ? { ...a, ...patch } : a)));
  }
  function remove(i: number) {
    onChange(assertions.filter((_, idx) => idx !== i));
  }
  function add() {
    onChange([...assertions, { path: "", op: "equals", value: "" }]);
  }

  return (
    <div className="flex flex-col gap-2">
      {assertions.map((a, i) => (
        <div
          key={i}
          className="flex flex-col gap-2 rounded-md border border-line bg-surface p-2.5 sm:flex-row sm:items-center"
        >
          <TextInput
            value={a.path}
            onChange={(e) => update(i, { path: e.target.value })}
            placeholder="$.field.path"
            className="font-mono text-xs sm:flex-1"
          />
          <select
            value={a.op}
            onChange={(e) => update(i, { op: e.target.value as AssertionOp })}
            className={`${selectClasses} sm:w-36`}
          >
            {ASSERTION_OPS.map((op) => (
              <option key={op} value={op}>
                {op}
              </option>
            ))}
          </select>
          {a.op !== "exists" && (
            <TextInput
              value={a.value}
              onChange={(e) => update(i, { value: e.target.value })}
              placeholder="value"
              className="font-mono text-xs sm:flex-1"
            />
          )}
          <Button type="button" variant="tertiary" size="sm" onClick={() => remove(i)}>
            Remove
          </Button>
        </div>
      ))}
      <div>
        <Button type="button" variant="secondary" size="sm" onClick={add}>
          + Add assertion
        </Button>
      </div>
    </div>
  );
}

function ToolCallsEditor({
  toolCalls,
  onChange,
}: {
  toolCalls: ToolCallDraft[];
  onChange: (next: ToolCallDraft[]) => void;
}) {
  function update(i: number, patch: Partial<ToolCallDraft>) {
    onChange(toolCalls.map((t, idx) => (idx === i ? { ...t, ...patch } : t)));
  }
  function remove(i: number) {
    onChange(toolCalls.filter((_, idx) => idx !== i));
  }
  function add() {
    onChange([...toolCalls, { tool: "", orderIndex: "", required: true, argsConstraints: [] }]);
  }

  return (
    <div className="flex flex-col gap-2">
      {toolCalls.map((t, i) => (
        <div key={i} className="flex flex-col gap-2 rounded-md border border-line bg-surface p-2.5">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
            <TextInput
              value={t.tool}
              onChange={(e) => update(i, { tool: e.target.value })}
              placeholder="tool_name"
              className="font-mono text-xs sm:flex-1"
            />
            <TextInput
              type="number"
              value={t.orderIndex}
              onChange={(e) => update(i, { orderIndex: e.target.value })}
              placeholder="order"
              className="text-xs sm:w-24"
            />
            <label className="flex shrink-0 items-center gap-1.5 text-xs text-ink-2">
              <input
                type="checkbox"
                checked={t.required}
                onChange={(e) => update(i, { required: e.target.checked })}
                className="h-3.5 w-3.5 accent-accent rounded border-line-strong text-accent focus-visible:ring-4 focus-visible:ring-accent/10"
              />
              Required
            </label>
            <Button type="button" variant="tertiary" size="sm" onClick={() => remove(i)}>
              Remove
            </Button>
          </div>
          <details className="group">
            <summary className="cursor-pointer list-none text-xs font-medium text-accent [&::-webkit-details-marker]:hidden">
              Argument constraints ({t.argsConstraints.length})
            </summary>
            <div className="mt-2">
              <AssertionsEditor
                assertions={t.argsConstraints}
                onChange={(next) => update(i, { argsConstraints: next })}
              />
            </div>
          </details>
        </div>
      ))}
      <div>
        <Button type="button" variant="secondary" size="sm" onClick={add}>
          + Add expected tool call
        </Button>
      </div>
    </div>
  );
}

/** A labeled section within the test case form — the same "uppercase
 * eyebrow label + border-t divider" idiom already used for read-side
 * grouping (see agents/[agentId]/page.tsx's Section component), applied
 * here so a ~15-field-group form reads as five coherent sections instead
 * of one long undifferentiated stack. Purely a layout wrapper — every
 * field's value/onChange/validation is unchanged. */
function FormSection({
  label,
  description,
  children,
}: {
  label: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <div className="border-t border-line pt-5 first:border-t-0 first:pt-0">
      <p className="text-xs font-semibold tracking-wide text-ink-3 uppercase">{label}</p>
      {description && <p className="mt-1 text-xs text-ink-3">{description}</p>}
      <div className="mt-3 flex flex-col gap-4">{children}</div>
    </div>
  );
}

/** Create/edit Test Case form — shared by both flows. In edit mode,
 * `initialCase` is a prop (not query data synced via effect), so its
 * form state is seeded once via a lazy useState initializer; the parent
 * page only mounts this component after the case has actually loaded. */
export function TestCaseForm({
  suiteId,
  initialCase,
  onSuccess,
  onCancel,
}: {
  suiteId: string;
  initialCase?: TestCaseRead;
  onSuccess: (testCase: TestCaseRead) => void;
  onCancel: () => void;
}) {
  const isEdit = initialCase !== undefined;
  const [initial] = useState<CaseFormState>(() => (initialCase ? toFormState(initialCase) : emptyFormState()));
  const [form, setForm] = useState<CaseFormState>(() => (initialCase ? toFormState(initialCase) : emptyFormState()));
  const [formError, setFormError] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: (payload: TestCaseCreate) => createTestCase(suiteId, payload),
    onSuccess,
  });
  const patchMutation = useMutation({
    mutationFn: (payload: TestCasePatch) => patchTestCase(initialCase!.id, payload),
    onSuccess,
  });
  const mutation = isEdit ? patchMutation : createMutation;

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setFormError(null);

    let input: Record<string, unknown>;
    try {
      input = JSON.parse(form.input || "{}");
    } catch {
      setFormError("Input must be valid JSON.");
      return;
    }

    let outputSchema: Record<string, unknown> | null = null;
    if (form.outputSchema.trim()) {
      try {
        outputSchema = JSON.parse(form.outputSchema);
      } catch {
        setFormError("Output schema must be valid JSON.");
        return;
      }
    }

    let metadata: Record<string, unknown> = {};
    if (form.metadata.trim()) {
      try {
        metadata = JSON.parse(form.metadata);
      } catch {
        setFormError("Metadata must be valid JSON.");
        return;
      }
    }

    const assertions = form.assertions.length > 0 ? draftsToAssertions(form.assertions) : null;
    const expectedToolCalls =
      form.expectedToolCalls.length > 0 ? draftsToToolCalls(form.expectedToolCalls) : null;

    if (!isEdit) {
      const payload: TestCaseCreate = {
        name: form.name.trim(),
        input,
        expected_output: form.expectedOutput.trim() || null,
        assertions,
        reference_context: form.referenceContext.trim() || null,
        expected_tool_calls: expectedToolCalls,
        rubric: form.rubric.trim() || null,
        expected_behavior: linesToArray(form.expectedBehavior),
        forbidden_behavior: linesToArray(form.forbiddenBehavior),
        allowed_tools: linesToArray(form.allowedTools),
        output_schema: outputSchema,
        latency_threshold_ms: form.latencyThresholdMs.trim() ? Number(form.latencyThresholdMs) : null,
        rubric_threshold: form.rubricThreshold.trim() ? Number(form.rubricThreshold) : 0.7,
        trial_count: form.trialCount.trim() ? Number(form.trialCount) : 1,
        tags: linesToArray(form.tags) ?? [],
        metadata,
      };
      createMutation.mutate(payload);
      return;
    }

    // Edit: only fields the user actually changed are sent — PATCH
    // /test-cases/{id} applies exactly the keys present in the request
    // body, then re-validates the *merged resulting* case's ground-truth
    // requirement server-side (app/services/test_suite_service.py).
    const payload: TestCasePatch = {};
    if (form.name !== initial.name) payload.name = form.name.trim();
    if (form.input !== initial.input) payload.input = input;
    if (form.expectedOutput !== initial.expectedOutput) {
      payload.expected_output = form.expectedOutput.trim() || null;
    }
    if (JSON.stringify(assertions) !== JSON.stringify(draftsToAssertions(initial.assertions))) {
      payload.assertions = assertions;
    }
    if (form.referenceContext !== initial.referenceContext) {
      payload.reference_context = form.referenceContext.trim() || null;
    }
    if (
      JSON.stringify(expectedToolCalls) !== JSON.stringify(draftsToToolCalls(initial.expectedToolCalls))
    ) {
      payload.expected_tool_calls = expectedToolCalls;
    }
    if (form.rubric !== initial.rubric) payload.rubric = form.rubric.trim() || null;
    if (form.expectedBehavior !== initial.expectedBehavior) {
      payload.expected_behavior = linesToArray(form.expectedBehavior);
    }
    if (form.forbiddenBehavior !== initial.forbiddenBehavior) {
      payload.forbidden_behavior = linesToArray(form.forbiddenBehavior);
    }
    if (form.allowedTools !== initial.allowedTools) {
      payload.allowed_tools = linesToArray(form.allowedTools);
    }
    if (form.outputSchema !== initial.outputSchema) payload.output_schema = outputSchema;
    if (form.latencyThresholdMs !== initial.latencyThresholdMs) {
      payload.latency_threshold_ms = form.latencyThresholdMs.trim() ? Number(form.latencyThresholdMs) : null;
    }
    if (form.rubricThreshold !== initial.rubricThreshold) {
      payload.rubric_threshold = form.rubricThreshold.trim() ? Number(form.rubricThreshold) : 0.7;
    }
    if (form.trialCount !== initial.trialCount) {
      payload.trial_count = form.trialCount.trim() ? Number(form.trialCount) : 1;
    }
    if (form.tags !== initial.tags) payload.tags = linesToArray(form.tags) ?? [];
    if (form.metadata !== initial.metadata) payload.metadata = metadata;

    if (Object.keys(payload).length === 0) {
      onCancel();
      return;
    }

    patchMutation.mutate(payload);
  }

  const groundTruthOk = hasGroundTruth(form);

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-5">
      <FormSection label="Basics">
        <Field
          label="Name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          required
        />

        <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
          Input (JSON)
          <textarea
            value={form.input}
            onChange={(e) => setForm({ ...form, input: e.target.value })}
            rows={4}
            className={`${textareaClasses} font-mono text-xs`}
          />
        </label>
      </FormSection>

      <FormSection
        label="Ground truth"
        description="What a correct response looks like — at least one of the five mechanisms below is required."
      >
        <div
          className={`rounded-md border px-3 py-2 text-xs ${
            groundTruthOk ? "border-line bg-surface-2 text-ink-3" : "border-warning/30 bg-warning-soft text-warning"
          }`}
        >
          {groundTruthOk
            ? "At least one ground-truth mechanism is set."
            : "At least one of expected output, assertions, reference context, expected tool calls, or rubric is required before this case can be saved."}
        </div>

        <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
          Expected output
          <textarea
            value={form.expectedOutput}
            onChange={(e) => setForm({ ...form, expectedOutput: e.target.value })}
            rows={2}
            placeholder="What the agent should produce"
            className={textareaClasses}
          />
        </label>

        <div>
          <p className="text-sm font-medium text-ink-2">Assertions</p>
          <p className="mt-0.5 text-xs text-ink-3">
            Checked against the agent&apos;s output at evaluation time — path, operator, value.
          </p>
          <div className="mt-2">
            <AssertionsEditor
              assertions={form.assertions}
              onChange={(next) => setForm({ ...form, assertions: next })}
            />
          </div>
        </div>

        <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
          Reference context
          <textarea
            value={form.referenceContext}
            onChange={(e) => setForm({ ...form, referenceContext: e.target.value })}
            rows={3}
            placeholder="Source context used for grounding evaluation"
            className={textareaClasses}
          />
        </label>

        <div>
          <p className="text-sm font-medium text-ink-2">Expected tool calls</p>
          <p className="mt-0.5 text-xs text-ink-3">
            The tool trajectory the agent is expected to follow, in order.
          </p>
          <div className="mt-2">
            <ToolCallsEditor
              toolCalls={form.expectedToolCalls}
              onChange={(next) => setForm({ ...form, expectedToolCalls: next })}
            />
          </div>
        </div>

        <div>
          <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
            Rubric
            <textarea
              value={form.rubric}
              onChange={(e) => setForm({ ...form, rubric: e.target.value })}
              rows={2}
              placeholder="Subjective grading criteria"
              className={textareaClasses}
            />
          </label>
          <p className="mt-1 text-xs text-ink-3">
            A rubric may require the LLM judge to resolve a verdict during suite execution — this
            form only stores the criteria, it never calls the judge.
          </p>
        </div>
      </FormSection>

      <FormSection
        label="Behavior constraints"
        description="What the agent must, and must never, do — independent of any single expected output."
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
            Expected behavior (one per line)
            <textarea
              value={form.expectedBehavior}
              onChange={(e) => setForm({ ...form, expectedBehavior: e.target.value })}
              rows={3}
              className={`${textareaClasses} font-mono text-xs`}
            />
          </label>
          <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
            Forbidden behavior (one per line)
            <textarea
              value={form.forbiddenBehavior}
              onChange={(e) => setForm({ ...form, forbiddenBehavior: e.target.value })}
              rows={3}
              className={`${textareaClasses} font-mono text-xs`}
            />
          </label>
          <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2 sm:col-span-2">
            Allowed tools (one per line)
            <textarea
              value={form.allowedTools}
              onChange={(e) => setForm({ ...form, allowedTools: e.target.value })}
              rows={3}
              className={`${textareaClasses} font-mono text-xs`}
            />
          </label>
        </div>
      </FormSection>

      <FormSection label="Execution settings">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field
            label="Rubric threshold (0–1)"
            type="number"
            min={0}
            max={1}
            step="0.05"
            value={form.rubricThreshold}
            onChange={(e) => setForm({ ...form, rubricThreshold: e.target.value })}
          />
          <Field
            label="Trial count"
            type="number"
            min={1}
            value={form.trialCount}
            onChange={(e) => setForm({ ...form, trialCount: e.target.value })}
          />
          <Field
            label="Latency threshold (ms)"
            type="number"
            min={1}
            value={form.latencyThresholdMs}
            onChange={(e) => setForm({ ...form, latencyThresholdMs: e.target.value })}
            placeholder="—"
          />
        </div>

        <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
          Output schema (JSON, optional)
          <textarea
            value={form.outputSchema}
            onChange={(e) => setForm({ ...form, outputSchema: e.target.value })}
            rows={4}
            placeholder="{}"
            className={`${textareaClasses} font-mono text-xs`}
          />
        </label>
      </FormSection>

      <FormSection label="Organization">
        <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
          Tags (one per line)
          <textarea
            value={form.tags}
            onChange={(e) => setForm({ ...form, tags: e.target.value })}
            rows={2}
            className={`${textareaClasses} font-mono text-xs`}
          />
        </label>

        <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2">
          Metadata (JSON)
          <textarea
            value={form.metadata}
            onChange={(e) => setForm({ ...form, metadata: e.target.value })}
            rows={3}
            className={`${textareaClasses} font-mono text-xs`}
          />
        </label>
      </FormSection>

      <div className="border-t border-line pt-5">
        <div className="flex items-center gap-2">
          <Button
            type="submit"
            variant="primary"
            disabled={mutation.isPending || !form.name.trim() || !groundTruthOk}
          >
            {mutation.isPending ? "Saving…" : isEdit ? "Save changes" : "Create test case"}
          </Button>
          <Button type="button" variant="tertiary" onClick={onCancel}>
            Cancel
          </Button>
        </div>

        {formError && <p className="mt-3 text-xs text-danger">{formError}</p>}
        {mutation.isError && (
          <p className="mt-3 text-xs text-danger">
            {mutation.error instanceof ApiError ? mutation.error.message : "Could not save this test case."}
          </p>
        )}
      </div>
    </form>
  );
}
