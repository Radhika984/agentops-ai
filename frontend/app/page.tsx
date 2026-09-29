"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "./components/ui/Button";
import {
  ArrowRightIcon,
  BrandMark,
  GoalIcon,
  PlanIcon,
  ReleaseIcon,
  SafetyIcon,
  ToolsIcon,
  VerifyIcon,
} from "./components/ui/icons";
import { StatusDot } from "./components/ui/Status";

// Read at build/runtime from the container environment (see docker-compose.yml).
// Falls back to localhost:8000 for `npm run dev` outside Docker.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type HealthState =
  | { status: "loading" }
  | { status: "ok" }
  | { status: "error"; message: string };

const PIPELINE_STAGES = [
  { icon: GoalIcon, label: "Goal", detail: "Define what the agent should accomplish" },
  { icon: PlanIcon, label: "Plan", detail: "Decompose the goal into an execution strategy" },
  { icon: ToolsIcon, label: "Tools", detail: "Call the tools required to make progress" },
  { icon: SafetyIcon, label: "Safety", detail: "Screen every tool call for risky actions" },
  { icon: VerifyIcon, label: "Verify", detail: "Check claims and outcomes against evidence" },
  { icon: ReleaseIcon, label: "Release", detail: "Ship, hold, or roll back — with a clear reason" },
] as const;

export default function Home() {
  const router = useRouter();
  const [health, setHealth] = useState<HealthState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;

    fetch(`${API_URL}/api/v1/health`)
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`Backend responded with status ${res.status}`);
        }
        return res.json();
      })
      .then(() => {
        if (!cancelled) setHealth({ status: "ok" });
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setHealth({
            status: "error",
            message: err instanceof Error ? err.message : "Unknown error",
          });
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="absolute inset-x-0 top-0 z-10 flex items-center justify-between px-6 py-5 md:px-10">
        <div className="flex items-center gap-2 text-sm font-semibold tracking-tight text-ink">
          <BrandMark className="text-accent" />
          AgentOps AI
        </div>
        <div className="flex items-center gap-5">
          <a
            href="#pipeline"
            className="hidden text-sm font-medium text-ink-2 no-underline transition-colors duration-150 hover:text-ink sm:inline md:text-shell-ink-2 md:hover:text-shell-ink"
          >
            How it works
          </a>
          <span className="hidden items-center gap-1.5 rounded-full border border-line-strong bg-surface px-2.5 py-1 text-xs font-medium text-ink-2 sm:inline-flex">
            {health.status === "loading" && <StatusDot tone="neutral" pulse />}
            {health.status === "ok" && <StatusDot tone="success" />}
            {health.status === "error" && <StatusDot tone="danger" />}
            {health.status === "ok" ? "Backend healthy" : health.status === "loading" ? "Checking…" : "Backend unreachable"}
          </span>
          <button
            onClick={() => router.push("/login")}
            className="text-sm font-medium text-ink-2 transition-colors duration-150 hover:text-ink md:text-shell-ink-2 md:hover:text-shell-ink"
          >
            Sign in
          </button>
        </div>
      </header>

      <main className="grid flex-1 md:grid-cols-2">
        {/* Left — the pitch, on the warm-light canvas. */}
        <div className="flex flex-col justify-center px-6 pt-28 pb-16 md:px-12 md:pt-24 lg:px-16">
          <div className="max-w-lg">
            <span className="animate-fade-in-up inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3 py-1 text-xs font-medium tracking-wide text-ink-2 uppercase">
              Evaluate · Observe · Release
            </span>

            <h1
              className="animate-fade-in-up mt-6 font-serif text-4xl leading-[1.12] text-ink md:text-5xl"
              style={{ animationDelay: "80ms" }}
            >
              Evaluate AI agents.
              <br />
              Before they reach <span className="text-accent">production.</span>
            </h1>

            <p
              className="animate-fade-in-up mt-5 text-base leading-relaxed text-ink-2"
              style={{ animationDelay: "150ms" }}
            >
              AgentOps evaluates agent behavior across planning, tools, safety, hallucinations,
              verification and cost — then hands you an auditable release decision, not a guess.
            </p>

            <div
              className="animate-fade-in-up mt-8 flex flex-wrap items-center gap-3"
              style={{ animationDelay: "220ms" }}
            >
              <Button variant="primary" onClick={() => router.push("/register")}>
                Get started
                <ArrowRightIcon />
              </Button>
              <Button variant="secondary" onClick={() => router.push("/login")}>
                Sign in
              </Button>
            </div>
          </div>

          {/* Pipeline preview — a real summary of what a run goes through,
              not marketing filler; matches the same stage vocabulary used
              in the run panel once signed in. */}
          <div
            id="pipeline"
            className="animate-fade-in-up mt-14 flex max-w-md flex-col gap-1"
            style={{ animationDelay: "300ms" }}
            aria-label="Agent evaluation pipeline"
          >
            {PIPELINE_STAGES.map((stage, i) => {
              const Icon = stage.icon;
              return (
                <div key={stage.label} className="relative flex items-start gap-3.5 py-2">
                  {i < PIPELINE_STAGES.length - 1 && (
                    <span
                      className="absolute top-9 left-3.75 h-[calc(100%-6px)] w-px bg-line-strong"
                      aria-hidden="true"
                    />
                  )}
                  <span
                    className="animate-node-pulse relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-line-strong bg-surface-elevated text-accent shadow-sm"
                    style={{ animationDelay: `${i * 1.1}s` }}
                  >
                    <Icon />
                  </span>
                  <div className="pt-1">
                    <p className="text-sm font-semibold text-ink">{stage.label}</p>
                    <p className="text-xs text-ink-3">{stage.detail}</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right — dark panel, decorative only: a technical-grid texture,
            a glowing orbit around the brand mark, and a few floating
            stage icons. Hidden on small screens to keep mobile clean and
            avoid squeezing the real content. */}
        <div className="bg-technical-grid-dark bg-radial-glow relative hidden overflow-hidden bg-shell-bg md:block">
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="relative flex h-104 w-104 items-center justify-center">
              <span
                className="animate-orbit-spin absolute inset-10 rounded-full border border-dashed border-shell-line-strong"
                aria-hidden="true"
              />
              <span
                className="absolute inset-20 rounded-full border border-shell-line"
                aria-hidden="true"
              />
              <span className="relative flex h-20 w-20 items-center justify-center rounded-full bg-shell-surface text-shell-accent shadow-lg">
                <BrandMark width={30} height={30} />
              </span>

              {/* Small floating stage cards — the same six-stage vocabulary
                  as the left column's list, echoed here as evidence "an
                  agent is moving through evaluation," not restated
                  marketing copy. Positioned at roughly the 12/2/4/6/8/10
                  o'clock points around the orbit ring. */}
              {[
                { Icon: GoalIcon, label: "Goal", top: "0%", left: "50%", delay: "0s" },
                { Icon: PlanIcon, label: "Plan", top: "18%", left: "88%", delay: "1.5s" },
                { Icon: ToolsIcon, label: "Tools", top: "68%", left: "92%", delay: "3s" },
                { Icon: SafetyIcon, label: "Safety", top: "94%", left: "50%", delay: "4.5s" },
                { Icon: VerifyIcon, label: "Verify", top: "68%", left: "4%", delay: "6s" },
                { Icon: ReleaseIcon, label: "Release", top: "18%", left: "4%", delay: "7.5s" },
              ].map(({ Icon, label, top, left, delay }, i) => (
                <span
                  key={i}
                  className="animate-float-slow absolute flex -translate-x-1/2 -translate-y-1/2 items-center gap-1.5 rounded-full border border-shell-line-strong bg-shell-surface py-1.5 pr-3 pl-1.5 text-xs font-medium text-shell-ink-2 shadow-md"
                  style={{ top, left, animationDelay: delay }}
                  aria-hidden="true"
                >
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-shell-accent-soft text-shell-accent">
                    <Icon width={13} height={13} />
                  </span>
                  {label}
                </span>
              ))}
            </div>
          </div>

          <p className="absolute bottom-10 left-1/2 w-full max-w-xs -translate-x-1/2 text-center text-xs leading-relaxed text-shell-ink-3">
            Every run is traced end-to-end — plan, tool calls, safety checks and verification, all
            inspectable after the fact.
          </p>
        </div>
      </main>

      <footer className="flex w-full items-center justify-between border-t border-line px-6 py-5 text-xs text-ink-3 md:px-10">
        <span>© {new Date().getFullYear()} AgentOps AI</span>
        <span className="flex items-center gap-1.5 sm:hidden">
          {health.status === "loading" && <StatusDot tone="neutral" pulse />}
          {health.status === "ok" && <StatusDot tone="success" />}
          {health.status === "error" && <StatusDot tone="danger" />}
          {health.status === "ok" ? "Backend healthy" : health.status === "loading" ? "Checking…" : "Backend unreachable"}
        </span>
      </footer>
    </div>
  );
}
