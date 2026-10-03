// Phase 0 design-audit screenshot harness (see the UI elevation brief).
// Captures every real route at three viewports into
// frontend/.design-shots/<phase>/ (gitignored — not shipped).
//
// Usage:
//   node scripts/design-audit-screenshots.mjs <phase> [--empty]
//
// Requires the app running at BASE_URL (default http://localhost:3000)
// and, for the non-empty pass, a seeded account (EMAIL/PASSWORD below,
// or override via env vars) with real data already created via the
// public API — this script only drives the browser, it never invents
// or seeds data itself.

import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const BASE_URL = process.env.DESIGN_AUDIT_BASE_URL ?? "http://localhost:3000";
const EMAIL = process.env.DESIGN_AUDIT_EMAIL ?? "designaudit@example.com";
const PASSWORD = process.env.DESIGN_AUDIT_PASSWORD ?? "DesignAudit123!";

const VIEWPORTS = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "laptop", width: 1024, height: 768 },
  { name: "mobile", width: 390, height: 844 },
];

// Real IDs from the seeded dev database (see scratchpad/seed.py) — never
// placeholders; a route that needs an ID that doesn't exist yet is
// simply left out below rather than faked.
const IDS = {
  projectId: "a64ac76d-2569-49d0-87c5-5d5d8f8b022c",
  agentId: "b97fd0b1-907e-4c5b-b59a-610748ece001",
  suiteId: "86f6b8cc-8f0e-495a-bc8d-6d14a766a0a8",
  caseId: "ac2c4f95-64ad-4cac-a40e-24db1aaa3d4e",
  candidateVersionId: "0e87b319-35c0-4f20-bd5d-ed23cf5b0adc",
  candidateRunId: "76c5bb1f-e97e-4362-970f-3a5c366f2146",
  cleanRunId: "05b9b65b-0c67-41a5-a1d4-5165252b2403",
  failResultId: "0cb09427-531c-4f97-b6d3-945dd0bf0d6f",
  passResultId: "fd526d8d-6f95-4fd5-9572-56bb3d5069c4",
  executionId: "7e4cf1a3-c20b-4f53-afd6-c7154a74a933",
};

const PUBLIC_ROUTES = [
  { name: "landing", path: "/" },
  { name: "login", path: "/login" },
  { name: "register", path: "/register" },
];

function authedRoutes(ids) {
  return [
    { name: "home", path: "/home" },
    { name: "projects", path: "/projects" },
    { name: "project-chat", path: `/projects/${ids.projectId}/chat` },
    { name: "agents", path: "/agents" },
    { name: "agent-detail", path: `/agents/${ids.agentId}` },
    { name: "agent-edit", path: `/agents/${ids.agentId}/edit` },
    { name: "agent-version-new", path: `/agents/${ids.agentId}/versions/new` },
    { name: "agent-test-invoke", path: `/agents/${ids.agentId}/versions/${ids.candidateVersionId}/test-invoke` },
    { name: "test-suite-new", path: `/agents/${ids.agentId}/test-suites/new` },
    { name: "test-suite-detail", path: `/agents/${ids.agentId}/test-suites/${ids.suiteId}` },
    { name: "test-suite-run-form", path: `/agents/${ids.agentId}/test-suites/${ids.suiteId}/run` },
    { name: "test-case-new", path: `/agents/${ids.agentId}/test-suites/${ids.suiteId}/test-cases/new` },
    { name: "test-case-edit", path: `/agents/${ids.agentId}/test-suites/${ids.suiteId}/test-cases/${ids.caseId}/edit` },
    { name: "suite-run-detail-candidate", path: `/agents/${ids.agentId}/test-suites/${ids.suiteId}/runs/${ids.candidateRunId}` },
    { name: "suite-run-regression", path: `/agents/${ids.agentId}/test-suites/${ids.suiteId}/runs/${ids.candidateRunId}/regression` },
    { name: "suite-run-release-hold", path: `/agents/${ids.agentId}/test-suites/${ids.suiteId}/runs/${ids.candidateRunId}/release` },
    { name: "suite-run-release-pass", path: `/agents/${ids.agentId}/test-suites/${ids.suiteId}/runs/${ids.cleanRunId}/release` },
    { name: "result-detail-fail", path: `/agents/${ids.agentId}/test-suites/${ids.suiteId}/runs/${ids.candidateRunId}/results/${ids.failResultId}` },
    { name: "result-detail-pass", path: `/agents/${ids.agentId}/test-suites/${ids.suiteId}/runs/${ids.candidateRunId}/results/${ids.passResultId}` },
    { name: "test-suites-nav", path: "/test-suites" },
    { name: "runs-nav", path: "/runs" },
    { name: "evaluation-nav", path: "/evaluation" },
    { name: "release-gate-nav", path: "/release-gate" },
    { name: "rca-nav", path: "/rca" },
    { name: "autofix-nav", path: "/autofix" },
    { name: "approvals-nav", path: "/approvals" },
    { name: "cost-nav", path: "/cost" },
    { name: "monitoring-nav", path: "/monitoring" },
    { name: "agent-version-monitoring", path: `/agent-versions/${ids.candidateVersionId}/monitoring` },
    { name: "execution-detail", path: `/agent-versions/${ids.candidateVersionId}/executions/${ids.executionId}` },
    { name: "settings", path: "/settings" },
  ];
}

// A smaller subset worth re-capturing from a completely fresh (no-data)
// account, to document the real empty state of each list/dashboard page.
const EMPTY_STATE_ROUTES = [
  "home",
  "projects",
  "agents",
  "test-suites-nav",
  "runs-nav",
  "evaluation-nav",
  "release-gate-nav",
  "rca-nav",
  "autofix-nav",
  "approvals-nav",
  "cost-nav",
  "monitoring-nav",
  "settings",
];

async function login(page, email, password) {
  await page.goto(`${BASE_URL}/login`, { waitUntil: "networkidle" });
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input[type="password"]').fill(password);
  await page.getByRole("button", { name: /sign in|log in/i }).click();
  await page.waitForURL(/\/home/, { timeout: 15000 });
}

async function shoot(page, outDir, name, viewport) {
  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  // Let layout/animations settle — short, fixed wait is fine for a
  // screenshot harness (not a correctness test).
  await page.waitForTimeout(350);
  const file = path.join(outDir, `${name}.${viewport.name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log("  ", file);
}

async function main() {
  const [, , phaseArg, ...rest] = process.argv;
  const phase = phaseArg ?? "phase0";
  const emptyMode = rest.includes("--empty");
  const outDir = path.resolve(".design-shots", phase, emptyMode ? "empty" : "seeded");
  await mkdir(outDir, { recursive: true });

  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();

  console.log("Public routes (unauthenticated):");
  for (const route of PUBLIC_ROUTES) {
    await page.goto(`${BASE_URL}${route.path}`, { waitUntil: "networkidle" });
    for (const vp of VIEWPORTS) await shoot(page, outDir, route.name, vp);
  }

  const email = emptyMode ? (process.env.DESIGN_AUDIT_EMPTY_EMAIL ?? "designaudit-empty@example.com") : EMAIL;
  const password = emptyMode ? (process.env.DESIGN_AUDIT_EMPTY_PASSWORD ?? "DesignAuditEmpty123!") : PASSWORD;

  console.log(`Logging in as ${email}...`);
  await login(page, email, password);

  const routes = authedRoutes(IDS).filter((r) => !emptyMode || EMPTY_STATE_ROUTES.includes(r.name));
  console.log(`Authenticated routes (${emptyMode ? "empty" : "seeded"} account):`);
  for (const route of routes) {
    try {
      await page.goto(`${BASE_URL}${route.path}`, { waitUntil: "networkidle", timeout: 20000 });
      // The release-review page never auto-evaluates (a deliberate "never
      // automatic" design) — click through so the screenshot captures the
      // real verdict band, not the pre-evaluation empty state.
      if (route.name.startsWith("suite-run-release")) {
        const evalButton = page.getByRole("button", { name: /run release gate evaluation/i });
        if (await evalButton.count()) {
          await evalButton.click();
          await page.waitForSelector("text=/PASS|HOLD/", { timeout: 10000 }).catch(() => {});
          await page.waitForLoadState("networkidle");
        }
      }
      for (const vp of VIEWPORTS) await shoot(page, outDir, route.name, vp);
    } catch (err) {
      console.error(`  FAILED ${route.path}:`, err.message);
    }
  }

  await browser.close();
  console.log("Done ->", outDir);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
