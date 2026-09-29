"use client";

import { useRef, useState, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { getCurrentUser, listApprovals, search, type SearchResult } from "../lib/api";
import {
  AgentIcon,
  ApprovalsIcon,
  BellIcon,
  BrandMark,
  ChevronDownIcon,
  CloseIcon,
  CostIcon,
  HomeIcon,
  LogoutIcon,
  MenuIcon,
  MonitoringIcon,
  ProjectsIcon,
  RCAIcon,
  ReleaseIcon,
  RunsIcon,
  SearchIcon,
  SettingsIcon,
  TestSuitesIcon,
  ToolsIcon,
  VerifyIcon,
} from "./ui/icons";

const SEARCH_KIND_LABEL: Record<string, string> = {
  project: "Project",
  agent: "Agent",
  test_suite: "Test Suite",
  test_case: "Test Case",
  agent_version: "Agent Version",
};

/** Real global search — backend/app/services/search_service.py, scoped
 * to the signed-in user's own Projects/Agents/TestSuites/TestCases/
 * AgentVersions. Debounced client-side (300ms) so every keystroke
 * doesn't issue a request; disabled below 2 characters, matching a
 * normal "start typing to search" affordance rather than querying on an
 * empty/1-char string. */
function GlobalSearch() {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  function handleChange(value: string) {
    setQuery(value);
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setDebounced(value), 300);
  }

  const searchQuery = useQuery({
    queryKey: ["search", debounced],
    queryFn: () => search(debounced),
    enabled: debounced.trim().length >= 2,
    staleTime: 10 * 1000,
  });

  function goTo(result: SearchResult) {
    setOpen(false);
    setQuery("");
    setDebounced("");
    router.push(result.href);
  }

  const results = searchQuery.data?.results ?? [];
  const showDropdown = open && debounced.trim().length >= 2;

  return (
    <div className="relative w-full max-w-md">
      <span className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-ink-3">
        <SearchIcon />
      </span>
      <input
        value={query}
        onChange={(e) => handleChange(e.target.value)}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Search projects, agents, test suites…"
        aria-label="Global search"
        className="w-full rounded-md border border-line-strong bg-surface py-2 pr-3 pl-9 text-sm text-ink placeholder:text-ink-3 backdrop-blur-md transition-all duration-150 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/15"
      />
      {showDropdown && (
        <div className="glass absolute top-full left-0 z-30 mt-2 w-full overflow-hidden rounded-lg border shadow-lg">
          {searchQuery.isLoading && (
            <p className="px-3 py-3 text-xs text-ink-3">Searching…</p>
          )}
          {searchQuery.isSuccess && results.length === 0 && (
            <p className="px-3 py-3 text-xs text-ink-3">No matches for &ldquo;{debounced}&rdquo;.</p>
          )}
          {results.map((result) => (
            <button
              key={`${result.kind}-${result.id}`}
              onMouseDown={() => goTo(result)}
              className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left text-sm text-ink transition-colors duration-150 hover:bg-surface-2"
            >
              <span className="min-w-0 truncate">{result.title}</span>
              <span className="shrink-0 text-[11px] text-ink-3">
                {SEARCH_KIND_LABEL[result.kind] ?? result.kind}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

interface NavItem {
  href: string;
  label: string;
  icon: (props: { className?: string }) => ReactNode;
}

// Every route here is a real, backed page — Home/Test Suites/Runs/
// Evaluation/Release Gate/RCA are account-wide views powered by the new
// dashboard/activity/results backend endpoints (see
// app/services/dashboard_service.py, activity_service.py,
// suite_run_service.py.list_all_results_for_owner()); AutoFix reuses the
// same real activity log, filtered. Approvals/Cost/Monitoring are the
// pre-existing real pages, kept exactly as they were — nothing removed.
const NAV_ITEMS: NavItem[] = [
  { href: "/home", label: "Home", icon: HomeIcon },
  { href: "/projects", label: "Projects", icon: ProjectsIcon },
  { href: "/agents", label: "Agents", icon: AgentIcon },
  { href: "/test-suites", label: "Test Suites", icon: TestSuitesIcon },
  { href: "/runs", label: "Runs", icon: RunsIcon },
  { href: "/evaluation", label: "Evaluation", icon: VerifyIcon },
  { href: "/release-gate", label: "Release Gate", icon: ReleaseIcon },
  { href: "/rca", label: "RCA", icon: RCAIcon },
  { href: "/autofix", label: "AutoFix", icon: ToolsIcon },
  { href: "/approvals", label: "Approvals", icon: ApprovalsIcon },
  { href: "/cost", label: "Cost", icon: CostIcon },
  { href: "/monitoring", label: "Monitoring", icon: MonitoringIcon },
];

const SETTINGS_ITEM: NavItem = { href: "/settings", label: "Settings", icon: SettingsIcon };

function NavLink({
  item,
  active,
  badge,
  onClick,
}: {
  item: NavItem;
  active: boolean;
  badge?: number;
  onClick?: () => void;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      onClick={onClick}
      className={`group relative flex items-center gap-2.5 rounded-lg py-2 pr-2.5 pl-3 text-sm font-medium no-underline transition-all duration-200 ${
        active
          ? "bg-linear-to-r from-shell-accent/30 via-shell-accent/15 to-transparent text-shell-ink shadow-[inset_0_1px_0_rgba(255,255,255,0.08),0_0_20px_-6px_var(--shell-accent)] hover:from-shell-accent/40 hover:via-shell-accent/20"
          : "text-shell-ink hover:bg-shell-surface-2 hover:text-shell-ink hover:translate-x-0.5"
      }`}
    >
      <span
        className={`absolute top-1/2 left-0 h-4 w-0.5 -translate-y-1/2 rounded-full bg-shell-accent transition-all duration-200 ${
          active ? "opacity-100 shadow-[0_0_8px_var(--shell-accent)]" : "opacity-0"
        }`}
        aria-hidden="true"
      />
      <Icon
        className={`shrink-0 transition-transform duration-200 ${active ? "" : "group-hover:scale-110"}`}
      />
      <span className="flex-1">{item.label}</span>
      {!!badge && badge > 0 && (
        <span className="flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-shell-accent px-1 text-[10px] font-semibold text-shell-bg tabular-nums">
          {badge}
        </span>
      )}
    </Link>
  );
}

function Brand({ tone = "shell" }: { tone?: "shell" | "light" }) {
  return (
    <Link
      href="/home"
      className={`flex items-center gap-2 px-1 py-1 text-sm font-semibold tracking-tight no-underline transition-opacity duration-150 hover:opacity-80 ${
        tone === "shell" ? "text-shell-ink" : "text-ink"
      }`}
    >
      <BrandMark className={tone === "shell" ? "text-shell-accent" : "text-accent"} />
      AgentOps AI
    </Link>
  );
}

/** Initial-in-a-circle avatar — no image upload exists in this app, and a
 * flat-colored initial reads as more intentional than a placeholder photo
 * or a generic person icon. Derived from the real signed-in user's email
 * (backend/app/routes/auth.py's /auth/me), never invented. */
function UserBadge({ email, loading }: { email: string | undefined; loading: boolean }) {
  const initial = email ? email.charAt(0).toUpperCase() : "";
  return (
    <div className="flex items-center gap-2.5 rounded-md px-3 py-2">
      <span className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-shell-accent-soft text-sm font-semibold text-shell-accent ring-1 ring-shell-line-strong">
        {loading ? "" : initial}
        <span
          className="absolute right-0 bottom-0 h-2 w-2 rounded-full bg-success ring-2 ring-shell-sidebar-bg"
          aria-hidden="true"
          title="Signed in"
        />
      </span>
      <div className="min-w-0">
        <p className="truncate text-xs font-medium text-shell-ink">
          {loading ? "Loading…" : (email ?? "Signed in")}
        </p>
        <p className="text-[11px] text-shell-ink-3">Signed in</p>
      </div>
    </div>
  );
}

/**
 * The authenticated application shell — a dark sidebar (desktop) + a dark
 * "app canvas" content area (the `.app-canvas` scoped token override in
 * globals.css), used by every page behind login (Projects, project chat,
 * Agents, Cost, Approvals, Monitoring). Every page keeps exactly the same
 * data/mutation logic and only hands this component its content plus an
 * onLogout callback and an optional breadcrumb.
 *
 * One continuous espresso surface, not a dark-panel-plus-light-canvas
 * split: the sidebar (--shell-* tokens) and the main content
 * (`.app-canvas`'s own override of the shared --surface/--ink family)
 * are two closely related dark tones rather than two different registers
 * — matching the reference composition's unified dark product shell. The
 * public landing/auth pages are untouched (`.app-canvas` is scoped to
 * this component's own root element only).
 */
export function AppShell({
  children,
  onLogout,
  breadcrumb,
}: {
  children: ReactNode;
  onLogout: () => void;
  breadcrumb?: ReactNode;
}) {
  const pathname = usePathname();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  const userQuery = useQuery({ queryKey: ["me"], queryFn: getCurrentUser, staleTime: 5 * 60 * 1000 });
  // The exact same query Approvals page (app/approvals/page.tsx) already
  // issues for its "pending" tab — react-query dedupes/shares the cache
  // entry by queryKey, so this doesn't add a second real request beyond
  // what that page already made if it's mounted. A real, already-plumbed
  // count, never a placeholder number.
  const pendingApprovalsQuery = useQuery({
    queryKey: ["approvals", "pending"],
    queryFn: () => listApprovals("pending"),
    staleTime: 30 * 1000,
  });
  const pendingApprovalsCount = pendingApprovalsQuery.data?.length;

  function navBadge(href: string): number | undefined {
    return href === "/approvals" ? pendingApprovalsCount : undefined;
  }

  return (
    <div className="app-canvas relative flex min-h-screen bg-background">
      <aside className="sidebar-grid relative hidden w-60 shrink-0 flex-col overflow-hidden border-r border-shell-line bg-shell-sidebar-bg px-3 py-4 md:flex">
        {/* Reference-fidelity decorative language: large organic blobs
            (asymmetric border-radius, never a plain circle) — one
            anchored upper/middle, extending in behind the nav list
            itself, and one anchored to the lower-left corner, bleeding
            off both the left and bottom edges. Opacity is deliberately
            high enough to read clearly at a glance (a decoration nobody
            can actually see is the same as not having one) while blur
            keeps every edge soft; the underlying brown base and darker
            espresso gaps between the shapes stay visible, so this never
            becomes one flat colored panel. Every shape here is
            aria-hidden/pointer-events-none and sits behind the
            `relative` nav/brand/user-area siblings below, so none of
            them can ever intercept a click. */}
        {/* blur-3xl (64px) was the actual reason these read as faint in
            practice despite high opacity numbers: a radial-gradient that
            already fades to transparent by ~70% of its own radius, then
            diffused across a 64px blur, spreads what little color exists
            over a huge area rather than concentrating it. blur-xl (24px)
            keeps only the very edge soft while the body of each shape
            reads as an actual curved form rather than a diffuse glow; a
            slight rotation on each one (and an elongated, non-circular
            aspect ratio) is what makes them read as flowing ribbons
            rather than blurred dots. The gradient still holds its peak
            color out to a wide radius before fading, so the shape itself
            (not just its outer glow) is what's visible. */}
        <div
          className="pointer-events-none absolute -top-20 left-4 h-96 w-80 opacity-85 blur-xl"
          style={{
            borderRadius: "32% 68% 58% 42% / 48% 36% 64% 52%",
            transform: "rotate(-14deg)",
            background:
              "radial-gradient(ellipse 70% 55% at 42% 32%, color-mix(in srgb, var(--shell-accent) 88%, transparent) 0%, color-mix(in srgb, var(--shell-accent) 62%, transparent) 48%, transparent 80%)",
          }}
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute -bottom-32 -left-20 h-104 w-96 opacity-80 blur-xl"
          style={{
            borderRadius: "66% 34% 52% 48% / 44% 46% 54% 56%",
            transform: "rotate(9deg)",
            background:
              "radial-gradient(ellipse 65% 55% at 58% 48%, color-mix(in srgb, var(--shell-accent) 82%, transparent) 0%, color-mix(in srgb, var(--shell-accent) 58%, transparent) 48%, transparent 80%)",
          }}
          aria-hidden="true"
        />
        {/* A cooler, rust-brown companion shape layered between the two
            main peach blobs, so the sidebar reads as several overlapping
            translucent forms rather than one uniform hue. */}
        <div
          className="pointer-events-none absolute top-1/4 -right-24 h-80 w-72 opacity-60 blur-lg"
          style={{
            borderRadius: "42% 58% 64% 36% / 58% 40% 60% 42%",
            transform: "rotate(-22deg)",
            background:
              "radial-gradient(ellipse 60% 50% at 48% 45%, color-mix(in srgb, #a8623f 88%, transparent) 0%, color-mix(in srgb, #a8623f 55%, transparent) 48%, transparent 78%)",
          }}
          aria-hidden="true"
        />
        <div
          className="app-glow-1 pointer-events-none absolute -top-16 -left-16 h-48 w-48 rounded-full opacity-30 blur-3xl"
          aria-hidden="true"
        />
        <Brand />
        <nav className="relative mt-7 flex flex-1 flex-col gap-0.5 overflow-y-auto">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.href}
              item={item}
              active={pathname.startsWith(item.href)}
              badge={navBadge(item.href)}
            />
          ))}
        </nav>
        <div className="relative flex flex-col gap-0.5 border-t border-shell-line pt-2">
          <NavLink item={SETTINGS_ITEM} active={pathname.startsWith(SETTINGS_ITEM.href)} />
        </div>
        <div className="relative flex flex-col gap-1 border-t border-shell-line pt-3">
          <UserBadge email={userQuery.data?.email} loading={userQuery.isLoading} />
          <button
            onClick={onLogout}
            className="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-shell-ink transition-colors duration-150 hover:bg-danger-soft hover:text-danger"
          >
            <LogoutIcon className="shrink-0" />
            Log out
          </button>
        </div>
      </aside>

      <div className="relative flex min-w-0 flex-1 flex-col">
        {/* Ambient atmosphere for the content column, not just a strip
            behind the header — two large, very-low-opacity warm blobs
            (see .app-glow-1/-2 in globals.css) that drift slowly (the
            existing --animate-float-slow token, reused rather than a
            new keyframe) and blend additively with the header's own
            .bg-radial-glow. `absolute` and scoped to THIS column (which
            is `relative`) rather than `fixed` to the viewport — a fixed,
            inset-0 layer would escape this column's bounds and paint
            over the sidebar too, which isn't the intent. Every child
            here is aria-hidden and pointer-events-none — decoration
            only, never intercepting a click or being read by a screen
            reader. */}
        <div className="pointer-events-none absolute inset-0 z-0 overflow-hidden" aria-hidden="true">
          <div className="app-glow-1 animate-float-slow absolute -top-40 right-[-10%] h-128 w-lg rounded-full opacity-[0.16] blur-3xl" />
          <div
            className="app-glow-2 animate-float-slow absolute top-1/3 -left-32 h-96 w-96 rounded-full opacity-[0.12] blur-3xl"
            style={{ animationDelay: "-3.5s" }}
          />
        </div>

        <header className="glass sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-line px-4 py-3 md:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <button
              onClick={() => setMobileNavOpen(true)}
              className="text-ink-2 transition-colors duration-150 hover:text-ink md:hidden"
              aria-label="Open navigation"
            >
              <MenuIcon />
            </button>
            <div className="min-w-0 md:hidden">
              <Brand tone="light" />
            </div>
            {breadcrumb && <div className="hidden min-w-0 md:block">{breadcrumb}</div>}
          </div>
          {/* Search sits toward the left of the remaining header space
              (its own max-w-md keeps it compact) rather than centered
              across the whole viewport — a flex-1 container with no
              justify-center lets it fall to the natural left edge of the
              space between the breadcrumb and the right-side icon group. */}
          <div className="hidden flex-1 items-center md:flex">
            <GlobalSearch />
          </div>
          <div className="flex shrink-0 items-center gap-1.5">
            {/* Real destination — Approvals, the one existing "things
                awaiting you" list — not an invented notification feed.
                Badge count reuses the same pending-approvals query the
                sidebar's nav badge already fetches (react-query dedupes
                it), so this is never a fabricated number. */}
            <Link
              href="/approvals"
              className="relative flex h-9 w-9 items-center justify-center rounded-full text-ink-2 transition-colors duration-150 hover:bg-surface-2 hover:text-ink"
              aria-label="Approvals awaiting your review"
            >
              <BellIcon />
              {!!pendingApprovalsCount && pendingApprovalsCount > 0 && (
                <span
                  className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-danger ring-2 ring-background"
                  aria-hidden="true"
                />
              )}
            </Link>
            <div className="relative">
              <button
                onClick={() => setUserMenuOpen((open) => !open)}
                onBlur={() => setTimeout(() => setUserMenuOpen(false), 150)}
                className="flex items-center gap-1.5 rounded-full py-1 pr-2 pl-1 transition-colors duration-150 hover:bg-surface-2"
                aria-label="Account menu"
                aria-expanded={userMenuOpen}
              >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-sm font-semibold text-accent ring-1 ring-line-strong">
                  {userQuery.isLoading
                    ? ""
                    : (userQuery.data?.email?.charAt(0).toUpperCase() ?? "")}
                </span>
                <ChevronDownIcon
                  className={`text-ink-3 transition-transform duration-150 ${userMenuOpen ? "rotate-180" : ""}`}
                />
              </button>
              {userMenuOpen && (
                <div className="glass absolute top-full right-0 z-30 mt-2 w-44 overflow-hidden rounded-lg border py-1 shadow-lg">
                  <p className="truncate border-b border-line px-3 py-2 text-xs text-ink-3">
                    {userQuery.data?.email ?? "Signed in"}
                  </p>
                  <Link
                    href="/settings"
                    className="block px-3 py-2 text-sm text-ink no-underline transition-colors duration-150 hover:bg-surface-2"
                  >
                    Settings
                  </Link>
                  <button
                    onMouseDown={onLogout}
                    className="block w-full px-3 py-2 text-left text-sm text-ink transition-colors duration-150 hover:bg-danger-soft hover:text-danger"
                  >
                    Log out
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>

        {breadcrumb && <div className="border-b border-line px-4 py-3 md:hidden">{breadcrumb}</div>}

        <main className="relative z-10 flex-1">{children}</main>
      </div>

      {mobileNavOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div
            className="absolute inset-0 bg-shell-bg/60"
            onClick={() => setMobileNavOpen(false)}
            aria-hidden="true"
          />
          <div className="animate-fade-in relative flex w-64 flex-col overflow-y-auto bg-shell-sidebar-bg px-3 py-4 shadow-lg">
            <div className="flex items-center justify-between">
              <Brand />
              <button
                onClick={() => setMobileNavOpen(false)}
                className="text-shell-sidebar-ink-2 transition-colors duration-150 hover:text-shell-ink"
                aria-label="Close navigation"
              >
                <CloseIcon />
              </button>
            </div>
            <nav className="mt-6 flex flex-col gap-0.5">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.href}
                  item={item}
                  active={pathname.startsWith(item.href)}
                  badge={navBadge(item.href)}
                  onClick={() => setMobileNavOpen(false)}
                />
              ))}
              <div className="mt-1 flex flex-col gap-0.5 border-t border-shell-line pt-2">
                <NavLink
                  item={SETTINGS_ITEM}
                  active={pathname.startsWith(SETTINGS_ITEM.href)}
                  onClick={() => setMobileNavOpen(false)}
                />
              </div>
            </nav>
            <div className="mt-auto flex flex-col gap-1 border-t border-shell-line pt-3">
              <UserBadge email={userQuery.data?.email} loading={userQuery.isLoading} />
              <button
                onClick={onLogout}
                className="flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-shell-ink transition-colors duration-150 hover:bg-shell-surface-2 hover:text-shell-ink"
              >
                <LogoutIcon className="shrink-0" />
                Log out
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
