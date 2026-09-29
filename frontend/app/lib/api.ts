// Typed fetch wrapper for the FastAPI backend. This is the only file that
// knows the API's URLs/request shapes — components call these functions,
// never fetch() directly, matching backend/app/ai/client.py's "one seam"
// pattern on the frontend side.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Token storage: localStorage, not an httpOnly cookie. The backend issues
// a Bearer token (OAuth2PasswordBearer), not a session cookie, so this
// matches its actual auth contract without requiring backend changes.
// Per the blueprint's own Phase 3 "Common Mistakes" note, this is a
// demo-appropriate tradeoff, not a production-ready one (XSS could read
// this token) — a production version would need the backend to issue
// httpOnly cookies instead, which is out of Phase 3's scope.
const TOKEN_KEY = "agentops_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

// BUG-001: FastAPI's own request-validation layer (a Pydantic field like
// UserCreate.email: EmailStr rejecting a malformed/reserved-domain
// address) never reaches a route handler at all, so it can't return the
// plain `{"detail": "<string>"}` shape every handler-raised domain error
// (NotFoundError, PermissionDeniedError, EmailAlreadyExistsError, ...)
// uses. FastAPI's own default 422 handler instead returns `{"detail":
// [{"loc": [...], "msg": "...", "type": "..."}, ...]}` — the extraction
// below only ever checked `typeof detail === "string"`, so this whole
// shape fell through to `res.statusText` ("Unprocessable Entity"),
// discarding the actual validation message. Each item's `msg` is already
// the real, human-readable explanation (e.g. "value is not a valid email
// address: ..."); this only reads it out, it doesn't change what the
// backend validates or how.
export function extractErrorDetail(data: unknown): string | null {
  const detail = (data as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (item && typeof item === "object" && typeof (item as { msg?: unknown }).msg === "string"
        ? (item as { msg: string }).msg
        : null))
      .filter((msg): msg is string => msg !== null);
    if (messages.length > 0) return messages.join("; ");
  }
  return null;
}

async function request<T>(
  path: string,
  options: { method?: string; body?: unknown; form?: Record<string, string>; auth?: boolean } = {},
): Promise<T> {
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;

  if (options.form) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    body = new URLSearchParams(options.form).toString();
  } else if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }

  const isAuthedRequest = options.auth !== false;
  if (isAuthedRequest) {
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}${path}`, {
    method: options.method ?? "GET",
    headers,
    body,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      const extracted = extractErrorDetail(data);
      if (extracted !== null) detail = extracted;
    } catch {
      // response body wasn't JSON — fall back to statusText
    }

    // A 401 on a request that sent a token means the backend rejected
    // it (expired, malformed, or the user no longer exists) — retrying
    // can never succeed with the same stored token. Clear it and send
    // the user back to /login instead of leaving every authenticated
    // page stuck showing this raw error with no way forward.
    if (
      isAuthedRequest &&
      res.status === 401 &&
      typeof window !== "undefined" &&
      window.location.pathname !== "/login"
    ) {
      clearToken();
      // A hard navigation, not useRouter().push(): this is a plain
      // module function, not a component, so no router instance is
      // available here — and a full reload is the correct choice
      // anyway, guaranteeing every cached query/component state from
      // the expired session is discarded, not just the token.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.href = "/login";
    }

    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ---- Types (mirror backend/app/schemas/*.py) ----

export interface UserRead {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  notify_on_suite_run_complete: boolean;
  notify_on_release_gate: boolean;
  notify_on_autofix_proposed: boolean;
  notify_on_approval_decided: boolean;
  created_at: string;
  updated_at: string;
}

export interface Token {
  access_token: string;
  token_type: string;
}

export interface ProjectRead {
  id: string;
  name: string;
  description: string | null;
  owner_id: string;
  created_at: string;
  updated_at: string;
}

export interface AskResponse {
  id: string;
  project_id: string;
  question: string;
  answer: string;
  confidence: number;
  created_at: string;
}

// No `confidence`: history entries are read back from the Interaction
// model, which never persisted a confidence score (see backend/app/schemas/ask.py).
export interface InteractionRead {
  id: string;
  project_id: string;
  question: string;
  answer: string;
  created_at: string;
}

// ---- Auth ----

export function register(email: string, password: string, fullName?: string): Promise<UserRead> {
  return request<UserRead>("/api/v1/auth/register", {
    method: "POST",
    auth: false,
    body: { email, password, full_name: fullName || undefined },
  });
}

export function login(email: string, password: string): Promise<Token> {
  return request<Token>("/api/v1/auth/login", {
    method: "POST",
    auth: false,
    form: { username: email, password },
  });
}

export function getCurrentUser(): Promise<UserRead> {
  return request<UserRead>("/api/v1/auth/me");
}

// ---- Projects ----

export function listProjects(): Promise<ProjectRead[]> {
  return request<ProjectRead[]>("/api/v1/projects");
}

export function createProject(name: string, description?: string): Promise<ProjectRead> {
  return request<ProjectRead>("/api/v1/projects", {
    method: "POST",
    body: { name, description: description || undefined },
  });
}

export function getProject(projectId: string): Promise<ProjectRead> {
  return request<ProjectRead>(`/api/v1/projects/${projectId}`);
}

// ---- Ask / interactions ----

export function askQuestion(projectId: string, question: string): Promise<AskResponse> {
  return request<AskResponse>(`/api/v1/projects/${projectId}/ask`, {
    method: "POST",
    body: { question },
  });
}

export function listInteractions(projectId: string): Promise<InteractionRead[]> {
  return request<InteractionRead[]>(`/api/v1/projects/${projectId}/ask`);
}

// ---- Runs (Phase 4: Planner -> Evaluation -> Verification agent graph) ----

export type RunStatus =
  | "pending"
  | "planning"
  | "evaluating"
  | "checking_hallucination"
  | "verifying"
  | "succeeded"
  | "failed";

export interface ToolCallRecord {
  tool_name: string;
  input: Record<string, unknown>;
  output: string;
  duration_ms: number;
  ok: boolean;
}

// Phase 7: one Safety block or Hallucination finding raised during a run
// (mirrors backend/app/agents/state.py's FlagRecord).
export interface FlagRecord {
  agent: string;
  type: string;
  severity: string;
  details: string;
}

// Phase 7: one OTel span from the run's execution (mirrors
// backend/app/observability/tracing.py's TraceSpanRecord). Not part of
// AgentState itself — stitched into the persisted state blob by
// run_repository.update_state()'s `extra` param, so it's optional here
// (a run persisted before Phase 7 won't have it).
export interface TraceSpanRecord {
  name: string;
  start_time_ns: number;
  duration_ms: number;
}

// Phase 9: the release-review workflow's snapshot (mirrors
// backend/app/approvals/service.py's ReleaseSnapshot). Not part of
// AgentState itself — stitched into the persisted state blob the same
// way `trace` is, only present once POST .../release has been called at
// least once for this run.
export interface ReleaseSnapshot {
  status: "analyzing_failure" | "awaiting_auto_fix_approval" | "awaiting_release_approval" | "done";
  root_cause: string | null;
  root_cause_pattern: string | null;
  auto_fix_proposed_task: string | null;
  auto_fix_applied: boolean;
  hard_gate_passed: boolean | null;
  soft_score: number | null;
  soft_score_components: Record<string, number>;
  decision: "ship" | "hold" | "rollback" | null;
  reason: string | null;
}

export interface RunState {
  goal: string;
  plan: string[];
  artifacts: Record<string, string>;
  evaluations: Array<{ score: number; passed: boolean }>;
  status: RunStatus;
  retry_count: number;
  verification_passed: boolean;
  tool_calls: ToolCallRecord[];
  retrieved_memory: string[];
  flags: FlagRecord[];
  trace?: TraceSpanRecord[];
  release?: ReleaseSnapshot;
}

export interface RunRead {
  id: string;
  project_id: string;
  goal: string;
  status: RunStatus;
  state: RunState;
  created_at: string;
  updated_at: string;
}

export function createRun(projectId: string, goal: string): Promise<RunRead> {
  return request<RunRead>(`/api/v1/projects/${projectId}/runs`, {
    method: "POST",
    body: { goal },
  });
}

export function getRun(projectId: string, runId: string): Promise<RunRead> {
  return request<RunRead>(`/api/v1/projects/${projectId}/runs/${runId}`);
}

// ---- Release review / approval queue (Phase 9) ----

export function requestRelease(projectId: string, runId: string): Promise<ReleaseSnapshot> {
  return request<ReleaseSnapshot>(`/api/v1/projects/${projectId}/runs/${runId}/release`, {
    method: "POST",
  });
}

// Phase 18: exactly one of run_id/suite_run_id is set (DB CHECK
// constraint on backend/app/models/approval.py) — both nullable here,
// matching backend/app/schemas/approval.py's ApprovalRead exactly. A
// legacy Run approval has suite_run_id=null; a SuiteRun-scoped approval
// (release_decision or auto_fix, Phase 18/19) has run_id=null.
export interface ApprovalRead {
  id: string;
  run_id: string | null;
  suite_run_id: string | null;
  node: string;
  status: "pending" | "approved" | "rejected";
  reason: string | null;
  requested_at: string;
  decided_by: string | null;
  decided_at: string | null;
}

export function listApprovals(statusFilter?: string): Promise<ApprovalRead[]> {
  const query = statusFilter ? `?status_filter=${encodeURIComponent(statusFilter)}` : "";
  return request<ApprovalRead[]>(`/api/v1/approvals${query}`);
}

// POST /approvals/{id}/decide returns ReleaseSnapshotRead for the legacy
// Run path, or the decided ApprovalRead itself for a SuiteRun-scoped
// approval (backend/app/api/v1/approvals.py) — there is no persisted
// ReleaseSnapshot for a SuiteRun approval, since its gate is computed
// fresh on every request (see release.ts's evaluateRelease()).
export function decideApproval(
  approvalId: string,
  approved: boolean,
  reason?: string,
): Promise<ReleaseSnapshot | ApprovalRead> {
  return request<ReleaseSnapshot | ApprovalRead>(`/api/v1/approvals/${approvalId}/decide`, {
    method: "POST",
    body: { approved, reason: reason || undefined },
  });
}

// ---- Cost dashboard (Phase 8: routing, cost, and caching) ----

export interface ModelGroupStats {
  agent: string;
  model_group: string;
  model: string;
  call_count: number;
  cache_hit_count: number;
  total_cost: number;
  avg_tokens_in: number;
  avg_tokens_out: number;
  // null when none of this (agent, model_group, model)'s calls were
  // linked to a run (e.g. agent="ask", which has no run concept).
  run_success_rate: number | null;
}

export interface CostRecommendation {
  agent: string;
  model_group: string;
  message: string;
}

export interface UsageReport {
  stats: ModelGroupStats[];
  recommendations: CostRecommendation[];
}

export function getCostDashboard(): Promise<UsageReport> {
  return request<UsageReport>("/api/v1/cost");
}

// ---- Post-release execution monitoring (Phase 20) ----
// Mirrors backend/app/schemas/production_execution.py exactly — these
// types describe what POST/GET /agent-versions/{id}/executions... and
// /agent-versions/{id}/monitoring actually return, nothing invented.

// A production execution's own reported tool call (backend/app/adapters/
// execution.py's ToolCallRecord) — duration_ms is optional there, unlike
// the legacy Run's ToolCallRecord above, so this is a distinct type
// rather than a reuse.
export interface ProductionToolCallRecord {
  tool_name: string;
  input: Record<string, unknown>;
  output: string;
  duration_ms: number | null;
  ok: boolean;
}

export interface ProductionTraceSpanRecord {
  name: string;
  start_time_ns: number | null;
  duration_ms: number | null;
}

// One Phase 13/15 evaluation check (backend/app/evaluation/models.py's
// Check) as persisted on a ProductionExecution.
export interface EvaluationCheck {
  check_type: string;
  status: "pass" | "fail" | "pending_llm" | "skipped" | "inconclusive";
  determinism: "deterministic" | "requires_llm";
  detail: string;
  metadata: Record<string, unknown>;
}

export type ExecutionVerdict = "PASS" | "FAIL" | "INCONCLUSIVE";

export interface ProductionExecutionRead {
  id: string;
  agent_version_id: string;
  external_execution_id: string;
  input: Record<string, unknown>;
  actual_output: unknown;
  tool_calls: ProductionToolCallRecord[];
  latency_ms: number | null;
  error: string | null;
  reference_context: string | null;
  trace: ProductionTraceSpanRecord[] | null;
  metadata: Record<string, unknown>;
  verdict: ExecutionVerdict;
  checks: EvaluationCheck[];
  created_at: string;
}

// The deterministic RCA whitelist (backend/app/rca/evidence.py),
// computed on read — only present on the detail response.
export interface RCAFinding {
  category: string;
  check_type: string;
  detail: string;
}

export interface ProductionExecutionDetail extends ProductionExecutionRead {
  rca_categories: RCAFinding[];
}

export interface ProductionMonitoringSummary {
  agent_version_id: string;
  total_executions: number;
  pass_count: number;
  fail_count: number;
  inconclusive_count: number;
  failure_rate: number | null;
  average_latency_ms: number | null;
  latency_threshold_violations: number;
  safety_failure_count: number;
  forbidden_tool_count: number;
  missing_required_tool_count: number;
  schema_failure_count: number;
  grounding_evaluated_count: number;
  grounding_failure_count: number;
}

export function listExecutions(versionId: string): Promise<ProductionExecutionRead[]> {
  return request<ProductionExecutionRead[]>(`/api/v1/agent-versions/${versionId}/executions`);
}

export function getExecution(
  versionId: string,
  executionId: string,
): Promise<ProductionExecutionDetail> {
  return request<ProductionExecutionDetail>(
    `/api/v1/agent-versions/${versionId}/executions/${executionId}`,
  );
}

export function getMonitoringSummary(versionId: string): Promise<ProductionMonitoringSummary> {
  return request<ProductionMonitoringSummary>(`/api/v1/agent-versions/${versionId}/monitoring`);
}

// ---- Regression candidates (Phase 20) ----
// Mirrors backend/app/schemas/test_suite.py's TestCaseRead — the same
// TestCase shape Phase 12 already established, now also carrying the
// Phase 20 `status`/`source_execution_id` fields.

export interface TestCaseRead {
  id: string;
  suite_id: string;
  name: string;
  input: Record<string, unknown>;
  history: Array<Record<string, unknown>> | null;
  reference_context: string | null;
  expected_output: string | null;
  assertions: Assertion[] | null;
  expected_tool_calls: ExpectedToolCall[] | null;
  rubric: string | null;
  expected_behavior: string[] | null;
  forbidden_behavior: string[] | null;
  allowed_tools: string[] | null;
  output_schema: Record<string, unknown> | null;
  latency_threshold_ms: number | null;
  rubric_threshold: number;
  trial_count: number;
  tags: string[];
  metadata: Record<string, unknown>;
  status: "active" | "candidate";
  source_execution_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface RegressionCandidateCreate {
  suite_id: string;
  name?: string;
  input?: Record<string, unknown>;
  reference_context?: string;
  expected_output?: string;
  assertions?: Assertion[];
  expected_tool_calls?: ExpectedToolCall[];
  rubric?: string;
  expected_behavior?: string[];
  forbidden_behavior?: string[];
  allowed_tools?: string[];
  output_schema?: Record<string, unknown>;
  latency_threshold_ms?: number;
}

export function createRegressionCandidate(
  executionId: string,
  payload: RegressionCandidateCreate,
): Promise<TestCaseRead> {
  return request<TestCaseRead>(`/api/v1/executions/${executionId}/regression-candidate`, {
    method: "POST",
    body: payload,
  });
}

export function acceptCandidateTestCase(caseId: string): Promise<TestCaseRead> {
  return request<TestCaseRead>(`/api/v1/test-cases/${caseId}/accept`, { method: "POST" });
}

// ---- Agent Registry (Phase 11) ----
// Mirrors backend/app/schemas/agent.py exactly. AgentCreate deliberately
// only has {project_id, name, description} — the default_* contract
// fields are PATCH-only (AgentUpdate), so they are not part of the
// create form, only the edit form.

export interface AgentRead {
  id: string;
  project_id: string;
  name: string;
  description: string | null;
  is_enabled: boolean;
  default_expected_behavior: string[] | null;
  default_forbidden_behavior: string[] | null;
  default_output_schema: Record<string, unknown> | null;
  default_latency_threshold_ms: number | null;
  default_allowed_tools: string[] | null;
  default_required_tools: string[] | null;
  min_call_interval_ms: number;
  default_timeout_ms: number;
  created_at: string;
  updated_at: string;
}

export interface AgentUpdate {
  name?: string;
  description?: string | null;
  is_enabled?: boolean;
  default_expected_behavior?: string[] | null;
  default_forbidden_behavior?: string[] | null;
  default_output_schema?: Record<string, unknown> | null;
  default_latency_threshold_ms?: number | null;
  default_allowed_tools?: string[] | null;
  default_required_tools?: string[] | null;
  min_call_interval_ms?: number;
  default_timeout_ms?: number;
}

export function listAgents(projectId: string): Promise<AgentRead[]> {
  return request<AgentRead[]>(`/api/v1/agents?project_id=${encodeURIComponent(projectId)}`);
}

export function createAgent(payload: {
  project_id: string;
  name: string;
  description?: string;
}): Promise<AgentRead> {
  return request<AgentRead>("/api/v1/agents", { method: "POST", body: payload });
}

export function getAgent(agentId: string): Promise<AgentRead> {
  return request<AgentRead>(`/api/v1/agents/${agentId}`);
}

export function updateAgent(agentId: string, payload: AgentUpdate): Promise<AgentRead> {
  return request<AgentRead>(`/api/v1/agents/${agentId}`, { method: "PATCH", body: payload });
}

// ---- Agent Versions (Phase 11) ----
// adapter_config is write-once (backend/app/models/agent_version.py) —
// there is deliberately no updateAgentVersion function; a config change
// means creating a new version instead.

export interface AgentVersionRead {
  id: string;
  agent_id: string;
  label: string;
  adapter_type: string;
  adapter_config: Record<string, unknown>;
  observability_level: number;
  is_baseline: boolean;
  created_at: string;
}

export interface AgentVersionCreate {
  label: string;
  adapter_type: "http" | "local";
  adapter_config: Record<string, unknown>;
  observability_level: number;
}

export function listAgentVersions(agentId: string): Promise<AgentVersionRead[]> {
  return request<AgentVersionRead[]>(`/api/v1/agents/${agentId}/versions`);
}

export function createAgentVersion(
  agentId: string,
  payload: AgentVersionCreate,
): Promise<AgentVersionRead> {
  return request<AgentVersionRead>(`/api/v1/agents/${agentId}/versions`, {
    method: "POST",
    body: payload,
  });
}

export function promoteBaseline(agentId: string, versionId: string): Promise<AgentVersionRead> {
  return request<AgentVersionRead>(`/api/v1/agents/${agentId}/versions/${versionId}/baseline`, {
    method: "POST",
  });
}

// ---- Test invoke (Phase 10/11) ----
// Mirrors backend/app/adapters/execution.py's AgentExecution exactly —
// the same normalized envelope every adapter returns. tool_calls/trace
// reuse the Phase 20 Production*Record shapes above since both mirror
// the identical backend Pydantic models (duration_ms/start_time_ns
// optional in both).

export interface AgentExecution {
  request_id: string;
  input: Record<string, unknown>;
  output: Record<string, unknown> | string | null;
  status: "ok" | "error" | "timeout";
  error: string | null;
  latency_ms: number;
  started_at: string;
  finished_at: string;
  tool_calls: ProductionToolCallRecord[];
  trace: ProductionTraceSpanRecord[] | null;
  token_usage: Record<string, unknown> | null;
  model_info: Record<string, unknown> | null;
  raw_response: Record<string, unknown> | null;
}

export function testInvokeAgentVersion(
  agentId: string,
  versionId: string,
  input: Record<string, unknown>,
): Promise<AgentExecution> {
  return request<AgentExecution>(`/api/v1/agents/${agentId}/versions/${versionId}/test-invoke`, {
    method: "POST",
    body: { input },
  });
}

// ---- Test Suites / Test Cases (Phase 12) ----
// Mirrors backend/app/schemas/test_suite.py and the assertion/expected
// -tool-call shapes defined in backend/app/evaluation/models.py exactly.
// GROUND_TRUTH_FIELDS below is the same five-field whitelist
// backend/app/services/test_suite_service.py enforces server-side — kept
// here only to drive client-side UX (disabling Save early); the backend
// remains the sole source of truth and re-validates independently.

export interface TestSuiteRead {
  id: string;
  agent_id: string;
  name: string;
  created_at: string;
  updated_at: string;
}

export function listTestSuites(agentId: string): Promise<TestSuiteRead[]> {
  return request<TestSuiteRead[]>(`/api/v1/agents/${agentId}/test-suites`);
}

export function createTestSuite(agentId: string, name: string): Promise<TestSuiteRead> {
  return request<TestSuiteRead>(`/api/v1/agents/${agentId}/test-suites`, {
    method: "POST",
    body: { name },
  });
}

// There is no GET /test-suites/{id} endpoint — a single suite is derived
// from the real list response rather than inventing one.
export async function getTestSuite(agentId: string, suiteId: string): Promise<TestSuiteRead> {
  const suites = await listTestSuites(agentId);
  const found = suites.find((s) => s.id === suiteId);
  if (!found) throw new ApiError(404, "Test suite not found.");
  return found;
}

// backend/app/evaluation/models.py's AssertionOp whitelist — nothing
// beyond this bounded set is ever sent or accepted.
export type AssertionOp =
  | "exists"
  | "equals"
  | "not_equals"
  | "contains"
  | "not_contains"
  | "gt"
  | "gte"
  | "lt"
  | "lte"
  | "length_eq";

export const ASSERTION_OPS: AssertionOp[] = [
  "exists",
  "equals",
  "not_equals",
  "contains",
  "not_contains",
  "gt",
  "gte",
  "lt",
  "lte",
  "length_eq",
];

export interface Assertion {
  path: string;
  op: AssertionOp;
  value?: unknown;
}

export interface ExpectedToolCall {
  tool: string;
  args_constraints?: Assertion[] | null;
  order_index?: number | null;
  required?: boolean;
}

export const GROUND_TRUTH_FIELDS = [
  "expected_output",
  "assertions",
  "reference_context",
  "expected_tool_calls",
  "rubric",
] as const;

export interface TestCaseCreate {
  name: string;
  input: Record<string, unknown>;
  reference_context?: string | null;
  expected_output?: string | null;
  assertions?: Assertion[] | null;
  expected_tool_calls?: ExpectedToolCall[] | null;
  rubric?: string | null;
  expected_behavior?: string[] | null;
  forbidden_behavior?: string[] | null;
  allowed_tools?: string[] | null;
  output_schema?: Record<string, unknown> | null;
  latency_threshold_ms?: number | null;
  rubric_threshold?: number;
  trial_count?: number;
  tags?: string[];
  metadata?: Record<string, unknown>;
}

export type TestCasePatch = Partial<TestCaseCreate>;

export function listTestCases(suiteId: string): Promise<TestCaseRead[]> {
  return request<TestCaseRead[]>(`/api/v1/test-suites/${suiteId}/test-cases`);
}

// There is no GET /test-cases/{id} endpoint — a single case is derived
// from the real list response rather than inventing one.
export async function getTestCase(suiteId: string, caseId: string): Promise<TestCaseRead> {
  const cases = await listTestCases(suiteId);
  const found = cases.find((c) => c.id === caseId);
  if (!found) throw new ApiError(404, "Test case not found.");
  return found;
}

export function createTestCase(suiteId: string, payload: TestCaseCreate): Promise<TestCaseRead> {
  return request<TestCaseRead>(`/api/v1/test-suites/${suiteId}/test-cases`, {
    method: "POST",
    body: payload,
  });
}

export function patchTestCase(caseId: string, payload: TestCasePatch): Promise<TestCaseRead> {
  return request<TestCaseRead>(`/api/v1/test-cases/${caseId}`, {
    method: "PATCH",
    body: payload,
  });
}

export function deleteTestCase(caseId: string): Promise<void> {
  return request<void>(`/api/v1/test-cases/${caseId}`, { method: "DELETE" });
}

// ---- Suite Runs / Results / Trials (Phase 14 + 16) ----
// Mirrors backend/app/schemas/suite_run.py and the trial-entry shape
// backend/app/services/suite_runner.py._evaluate_trial() actually
// persists into TestCaseResult.trials[] exactly — nothing invented.

// backend/app/models/suite_run.py's CHECK constraint whitelist.
export type SuiteRunStatus = "pending" | "running" | "cancelling" | "completed" | "failed";

export interface SuiteRunRead {
  id: string;
  suite_id: string;
  agent_version_id: string;
  status: SuiteRunStatus;
  started_at: string | null;
  completed_at: string | null;
  pass_count: number;
  fail_count: number;
  inconclusive_count: number;
  skipped_count: number;
  llm_judge_invocation_count: number;
  max_concurrency: number;
  created_at: string;
}

export interface SuiteRunCreate {
  agent_version_id: string;
  max_concurrency?: number;
}

export function createSuiteRun(suiteId: string, payload: SuiteRunCreate): Promise<SuiteRunRead> {
  return request<SuiteRunRead>(`/api/v1/test-suites/${suiteId}/runs`, {
    method: "POST",
    body: payload,
  });
}

export function getSuiteRun(suiteRunId: string): Promise<SuiteRunRead> {
  return request<SuiteRunRead>(`/api/v1/suite-runs/${suiteRunId}`);
}

// backend/app/adapters/execution.py's AgentExecution.status, reused
// as-is for a trial's own "status" field (or "error" for a trial whose
// adapter/config failed before producing an AgentExecution at all).
export type TrialStatus = "ok" | "error" | "timeout";

export type Verdict = "PASS" | "FAIL" | "INCONCLUSIVE";

export interface TrialEntry {
  trial_index: number;
  verdict: Verdict;
  status: TrialStatus;
  checks: EvaluationCheck[];
  actual_output: unknown;
  latency_ms: number | null;
  error: string | null;
  llm_judge_invoked: boolean;
}

export interface TestCaseResultRead {
  id: string;
  suite_run_id: string;
  test_case_id: string;
  verdict: Verdict;
  verdict_method: string;
  checks: EvaluationCheck[];
  trials: TrialEntry[];
  actual_output: unknown;
  latency_ms: number | null;
  error: string | null;
  suggested_fix: string | null;
  created_at: string;
  updated_at: string;
}

export function listSuiteRunResults(suiteRunId: string): Promise<TestCaseResultRead[]> {
  return request<TestCaseResultRead[]>(`/api/v1/suite-runs/${suiteRunId}/results`);
}

export function getSuiteRunResult(
  suiteRunId: string,
  resultId: string,
): Promise<TestCaseResultRead> {
  return request<TestCaseResultRead>(`/api/v1/suite-runs/${suiteRunId}/results/${resultId}`);
}

// ---- Regression (Phase 17) ----
// Mirrors backend/app/schemas/regression.py exactly — every field here is
// computed on read by the backend from two already-persisted SuiteRuns;
// nothing is recomputed client-side.

export type RegressionClassification = "regression" | "improvement" | "unchanged" | "changed";

export interface OutputDiff {
  baseline_output: unknown;
  candidate_output: unknown;
  output_changed: boolean;
}

export interface ToolTrajectoryDiff {
  baseline_tools: string[];
  candidate_tools: string[];
  added_tools: string[];
  removed_tools: string[];
  order_changed: boolean;
  argument_changes: string[];
  changed: boolean;
}

export interface LatencyDiff {
  baseline_latency_ms: number | null;
  candidate_latency_ms: number | null;
  delta_ms: number | null;
  available: boolean;
  changed: boolean;
}

export interface SafetyDiff {
  baseline_status: string;
  candidate_status: string;
  newly_unsafe: string[];
  resolved: string[];
  changed: boolean;
}

export interface GroundingDiff {
  baseline_status: string | null;
  candidate_status: string | null;
  changed: boolean;
}

export interface TrialSummaryDiff {
  baseline_trial_verdicts: string[];
  candidate_trial_verdicts: string[];
}

export interface CaseComparison {
  test_case_id: string;
  classification: RegressionClassification;
  baseline_verdict: string;
  candidate_verdict: string;
  output_diff: OutputDiff;
  tool_trajectory_diff: ToolTrajectoryDiff;
  latency_diff: LatencyDiff;
  safety_diff: SafetyDiff;
  grounding_diff: GroundingDiff;
  trial_summary: TrialSummaryDiff;
}

export interface RegressionSummary {
  total_matched_cases: number;
  regressions: number;
  improvements: number;
  unchanged: number;
  changed: number;
  new_cases: number;
  missing_cases: number;
  baseline_pass_count: number;
  candidate_pass_count: number;
  baseline_fail_count: number;
  candidate_fail_count: number;
  baseline_inconclusive_count: number;
  candidate_inconclusive_count: number;
  baseline_skipped_count: number;
  candidate_skipped_count: number;
  baseline_pass_rate: number | null;
  candidate_pass_rate: number | null;
  pass_rate_delta: number | null;
  baseline_inconclusive_rate: number | null;
  candidate_inconclusive_rate: number | null;
  inconclusive_rate_delta: number | null;
  safety_changes: number;
  grounding_changes: number;
  latency_changes: number;
  tool_changes: number;
}

export interface RegressionResponse {
  suite_id: string;
  baseline_suite_run_id: string;
  baseline_agent_version_id: string;
  candidate_suite_run_id: string;
  candidate_agent_version_id: string;
  summary: RegressionSummary;
  cases: CaseComparison[];
  new_test_case_ids: string[];
  missing_test_case_ids: string[];
}

// The baseline side is never supplied by the caller — the backend
// determines it (latest SuiteRun of the AgentVersion with
// is_baseline=true) — only the candidate SuiteRun id is a parameter.
export function getRegression(suiteId: string, candidateRunId: string): Promise<RegressionResponse> {
  return request<RegressionResponse>(
    `/api/v1/test-suites/${suiteId}/regression?candidate_run_id=${encodeURIComponent(candidateRunId)}`,
  );
}

// ---- RCA (Phase 18) ----
// Mirrors backend/app/schemas/rca.py exactly. No confidence field exists
// on the backend response, so none is displayed.

export type RCATier = "deterministic" | "llm_hypothesis" | "insufficient_evidence" | "not_applicable";

export interface RCAEvidenceItem {
  check_type: string;
  status: string | null;
  detail: string;
}

export interface RCARegressionEvidence {
  baseline_verdict: string;
  candidate_verdict: string;
  classification: string;
  output_changed: boolean;
  tool_changed: boolean;
  safety_changed: boolean;
  grounding_changed: boolean;
}

export interface RCAResponse {
  test_case_id: string;
  suite_run_id: string;
  verdict: string;
  tier: RCATier;
  root_cause_category: string | null;
  all_matched_categories: string[];
  explanation: string;
  evidence_references: RCAEvidenceItem[];
  related_check_types: string[];
  trace_span_ids: string[];
  regression: RCARegressionEvidence | null;
}

export function getRCA(suiteRunId: string, resultId: string): Promise<RCAResponse> {
  return request<RCAResponse>(`/api/v1/suite-runs/${suiteRunId}/results/${resultId}/rca`);
}

// ---- Release Gate (Phase 18) ----
// Mirrors backend/app/schemas/release.py exactly. Evaluating this is the
// release action itself: when the hard gate passes, the backend
// idempotently ensures a pending Approval(node="release_decision") row
// exists (app/services/release_gate_service.py) — there is no separate
// "confirm release" endpoint.

export type ReleaseDecisionValue = "pass" | "hold";

export interface HardGateReasonRead {
  category: string;
  test_case_id: string;
  check_type: string;
  detail: string;
}

export interface RegressionSoftInput {
  available: boolean;
  regression_count: number | null;
  improvement_count: number | null;
  pass_rate_delta: number | null;
}

export interface ReleaseDecisionResponse {
  suite_run_id: string;
  decision: ReleaseDecisionValue;
  hard_gate_passed: boolean;
  hard_gate_reasons: HardGateReasonRead[];
  approval_required: boolean;
  total_cases: number;
  pass_count: number;
  fail_count: number;
  inconclusive_count: number;
  pass_rate: number | null;
  inconclusive_rate: number | null;
  safety_flag_count: number;
  forbidden_tool_count: number;
  missing_required_tool_count: number;
  schema_failure_count: number;
  rubric_case_count: number;
  regression: RegressionSoftInput;
  soft_score: number;
  soft_score_components: Record<string, number>;
  reason: string;
}

export function evaluateRelease(suiteRunId: string): Promise<ReleaseDecisionResponse> {
  return request<ReleaseDecisionResponse>(`/api/v1/suite-runs/${suiteRunId}/release`, {
    method: "POST",
  });
}

// ---- AutoFix (Phase 19) ----
// Mirrors backend/app/schemas/autofix.py exactly. This is the ONLY
// AutoFix endpoint — there is no separate apply/retry endpoint. Options
// 1-3 (testcase_edit/agent_default_edit/trial_count_increase) create a
// pending Approval(node="auto_fix") applied only through the EXISTING
// POST /approvals/{id}/decide flow when approved; Option 4
// (owner_suggestion) writes TestCaseResult.suggested_fix directly and
// needs no approval. AutoFix never reads or writes
// AgentVersion.adapter_config (backend/app/autofix/proposal.py never
// imports that model/column) — this client mirrors that: there is no
// function here that submits an adapter_config value.

export type AutoFixOption =
  | "testcase_edit"
  | "agent_default_edit"
  | "trial_count_increase"
  | "owner_suggestion";

// The one real label set for AutoFixOption — previously redefined
// identically in 2 separate page files (result detail, approvals);
// centralized here alongside the type it labels, following this file's
// own existing convention (see ASSERTION_OPS/GROUND_TRUTH_FIELDS above).
export const AUTOFIX_OPTION_LABEL: Record<AutoFixOption, string> = {
  testcase_edit: "Edit test case",
  agent_default_edit: "Edit agent default",
  trial_count_increase: "Increase trial count",
  owner_suggestion: "Suggestion",
};

export interface AutoFixProposalRead {
  option: AutoFixOption;
  rca_category: string | null;
  field: string | null;
  current_value: unknown;
  proposed_value: unknown;
  rationale: string;
  requires_approval: boolean;
  approval_id: string | null;
  suggested_fix_recorded: boolean;
}

export function proposeAutoFix(
  suiteRunId: string,
  resultId: string,
  preferAgentDefault = false,
): Promise<AutoFixProposalRead> {
  const query = preferAgentDefault ? "?prefer_agent_default=true" : "";
  return request<AutoFixProposalRead>(
    `/api/v1/suite-runs/${suiteRunId}/results/${resultId}/autofix${query}`,
    { method: "POST" },
  );
}

// The structured payload backend/app/services/autofix_service.py
// round-trips as JSON text inside Approval.reason for node="auto_fix"
// rows only (a "release_decision" row's reason stays plain text) — see
// that module's own docstring. Parsed defensively on the frontend since
// it is untrusted-shaped text from this layer's point of view, exactly
// how backend/app/autofix/apply.py itself treats it before applying.
export interface AutoFixReverification {
  suite_run_id: string;
  new_verdict: string | null;
  resolved: boolean;
}

export interface AutoFixApprovalPayload {
  autofix: true;
  action: AutoFixOption;
  test_case_id: string;
  test_case_result_id: string;
  suite_run_id: string;
  suite_id: string;
  agent_id: string;
  agent_version_id: string;
  rca_category: string | null;
  field: string | null;
  current_value: unknown;
  proposed_value: unknown;
  rationale: string;
  decision_reason?: string | null;
  reverification?: AutoFixReverification;
}

// ---- Home dashboard (real, owner-scoped aggregation reads only) ----
// Mirrors backend/app/schemas/dashboard.py exactly.

export interface DashboardStats {
  total_projects: number;
  total_agents: number;
  total_suite_runs: number;
  release_gate_holds: number;
}

export function getDashboardStats(): Promise<DashboardStats> {
  return request<DashboardStats>("/api/v1/dashboard/stats");
}

export interface SuiteRunSummary {
  id: string;
  suite_id: string;
  suite_name: string;
  agent_id: string;
  agent_name: string;
  project_id: string;
  project_name: string;
  agent_version_id: string;
  version_label: string;
  status: SuiteRunStatus;
  verdict: Verdict | null;
  pass_count: number;
  fail_count: number;
  inconclusive_count: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface SuiteRunListResponse {
  items: SuiteRunSummary[];
  total: number;
}

export function getRecentSuiteRuns(limit = 20, offset = 0): Promise<SuiteRunListResponse> {
  return request<SuiteRunListResponse>(
    `/api/v1/dashboard/recent-suite-runs?limit=${limit}&offset=${offset}`,
  );
}

// The account-wide "Runs" nav page — the exact same real capability as
// getRecentSuiteRuns() above (backend/app/api/v1/suite_runs.py's
// list_all_suite_runs()), just a different route/page size.
export function listAllSuiteRuns(limit = 20, offset = 0): Promise<SuiteRunListResponse> {
  return request<SuiteRunListResponse>(
    `/api/v1/suite-runs?limit=${limit}&offset=${offset}`,
  );
}

export interface VerdictDistribution {
  pass_count: number;
  fail_count: number;
  inconclusive_count: number;
  total: number;
}

export function getVerdictDistribution(): Promise<VerdictDistribution> {
  return request<VerdictDistribution>("/api/v1/dashboard/verdict-distribution");
}

export interface PerformancePoint {
  date: string;
  pass_rate: number;
  fail_rate: number;
  inconclusive_rate: number;
  total_results: number;
}

export interface PerformanceOverview {
  points: PerformancePoint[];
  range_days: number;
}

export function getPerformanceOverview(days = 7): Promise<PerformanceOverview> {
  return request<PerformanceOverview>(`/api/v1/dashboard/performance?days=${days}`);
}

// ---- Recent Activity (real, persisted product events) ----
// Mirrors backend/app/schemas/activity.py exactly.

export interface ActivityEventRead {
  id: string;
  event_type: string;
  title: string;
  description: string | null;
  entity_type: string | null;
  entity_id: string | null;
  event_metadata: Record<string, unknown>;
  created_at: string;
}

export function listActivity(limit = 20, eventType?: string): Promise<ActivityEventRead[]> {
  const query = eventType ? `&event_type=${encodeURIComponent(eventType)}` : "";
  return request<ActivityEventRead[]>(`/api/v1/activity?limit=${limit}${query}`);
}

// ---- Settings > API Keys ----
// Mirrors backend/app/schemas/api_key.py exactly. The raw key is present
// ONLY in ApiKeyCreateResponse, returned once, from createApiKey() —
// never persisted client-side, never retrievable again after this call
// returns (see that endpoint's own backend docstring).

export interface ApiKeyRead {
  id: string;
  name: string;
  key_prefix: string;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface ApiKeyCreateResponse {
  id: string;
  name: string;
  key_prefix: string;
  api_key: string;
  created_at: string;
}

export function createApiKey(name: string): Promise<ApiKeyCreateResponse> {
  return request<ApiKeyCreateResponse>("/api/v1/api-keys", { method: "POST", body: { name } });
}

export function listApiKeys(): Promise<ApiKeyRead[]> {
  return request<ApiKeyRead[]>("/api/v1/api-keys");
}

export function revokeApiKey(keyId: string): Promise<void> {
  return request<void>(`/api/v1/api-keys/${keyId}`, { method: "DELETE" });
}

// ---- Global search ----
// Mirrors backend/app/schemas/search.py exactly. Searches only real,
// owner-scoped Projects/Agents/TestSuites/TestCases/AgentVersions — see
// that endpoint's own backend docstring for why SuiteRun is excluded
// (no real name/label field to match against).

export interface SearchResult {
  kind: string;
  id: string;
  title: string;
  subtitle: string | null;
  href: string;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
}

export function search(query: string): Promise<SearchResponse> {
  return request<SearchResponse>(`/api/v1/search?q=${encodeURIComponent(query)}`);
}

// ---- Account-wide "Test Suites" / "Evaluation" / "RCA" nav pages ----

export function listAllTestSuites(): Promise<TestSuiteRead[]> {
  return request<TestSuiteRead[]>("/api/v1/test-suites");
}

export interface TestCaseResultSummary {
  id: string;
  suite_run_id: string;
  test_case_id: string;
  test_case_name: string;
  suite_id: string;
  suite_name: string;
  agent_id: string;
  agent_name: string;
  verdict: Verdict;
  latency_ms: number | null;
  error: string | null;
  created_at: string;
}

export interface TestCaseResultListResponse {
  items: TestCaseResultSummary[];
  total: number;
}

export function listAllResults(
  options: { verdicts?: Verdict[]; limit?: number; offset?: number } = {},
): Promise<TestCaseResultListResponse> {
  const { verdicts, limit = 20, offset = 0 } = options;
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (verdicts && verdicts.length > 0) params.set("verdicts", verdicts.join(","));
  return request<TestCaseResultListResponse>(`/api/v1/results?${params.toString()}`);
}

// ---- Settings > Profile / Security / Notification Preferences ----
// Mirrors backend/app/schemas/user.py's UserUpdate/PasswordChange/
// NotificationPreferences exactly.

export function updateProfile(fullName: string | null): Promise<UserRead> {
  return request<UserRead>("/api/v1/auth/me", { method: "PATCH", body: { full_name: fullName } });
}

export function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  return request<void>("/api/v1/auth/me/password", {
    method: "PATCH",
    body: { current_password: currentPassword, new_password: newPassword },
  });
}

export interface NotificationPreferences {
  notify_on_suite_run_complete: boolean;
  notify_on_release_gate: boolean;
  notify_on_autofix_proposed: boolean;
  notify_on_approval_decided: boolean;
}

export function getNotificationPreferences(): Promise<NotificationPreferences> {
  return request<NotificationPreferences>("/api/v1/auth/me/notifications");
}

export function updateNotificationPreferences(
  prefs: NotificationPreferences,
): Promise<NotificationPreferences> {
  return request<NotificationPreferences>("/api/v1/auth/me/notifications", {
    method: "PATCH",
    body: prefs,
  });
}
