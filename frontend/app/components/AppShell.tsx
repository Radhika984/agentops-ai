"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
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
  ReleaseIcon,
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
 * empty/1-char string. A real Cmd/Ctrl+K shortcut focuses the field —
 * the "keyboard hints, shown cleanly" the v2 brief asks for. */
function GlobalSearch() {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const [open, setOpen] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

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
    <div className="relative mx-auto w-full max-w-xl">
      <span className="pointer-events-none absolute top-1/2 left-4 -translate-y-1/2 text-ink-3">
        <SearchIcon />
      </span>
      <input
        ref={inputRef}
        id="global-search-input"
        value={query}
        onChange={(e) => handleChange(e.target.value)}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="Search agents, runs, test suites, or ask anything…"
        aria-label="Global search"
        className="w-full rounded-full border border-line-strong bg-surface py-2.5 pr-16 pl-10 text-sm text-ink placeholder:text-ink-3 transition-all duration-150 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/15"
      />
      {query.length === 0 && (
        <span
          className="pointer-events-none absolute top-1/2 right-3 flex -translate-y-1/2 items-center gap-1"
          aria-hidden="true"
        >
          <kbd className="rounded border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-ink-3">
            &#8984;
          </kbd>
          <kbd className="rounded border border-line-strong bg-surface-2 px-1.5 py-0.5 font-mono text-[10px] text-ink-3">
            K
          </kbd>
        </span>
      )}
      {showDropdown && (
        <div className="glass absolute top-full left-0 z-30 mt-2 w-full overflow-hidden rounded-float border shadow-lg">
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

// A single flat list (no section headers) — every route here is still the
// exact same real, backed page as before (see git history), just presented
// as one continuous list rather than grouped by lifecycle stage. Runs and
// RCA keep their routes and are still reachable from the lifecycle rail /
// recent-activity rows on Home; they're just not primary nav entries here.
const NAV_ITEMS: NavItem[] = [
  { href: "/home", label: "Overview", icon: HomeIcon },
  { href: "/projects", label: "Projects", icon: ProjectsIcon },
  { href: "/agents", label: "Agents", icon: AgentIcon },
  { href: "/test-suites", label: "Test Suites", icon: TestSuitesIcon },
  { href: "/evaluation", label: "Evaluation", icon: VerifyIcon },
  { href: "/release-gate", label: "Release Gate", icon: ReleaseIcon },
  { href: "/autofix", label: "AutoFix", icon: ToolsIcon },
  { href: "/approvals", label: "Approvals", icon: ApprovalsIcon },
  { href: "/monitoring", label: "Monitoring", icon: MonitoringIcon },
  { href: "/cost", label: "Cost", icon: CostIcon },
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
      // Color lives on the inner span, not this <a>: globals.css's
      // unlayered `a { color: inherit }` reset (see its own comment)
      // always beats a layered Tailwind text-color utility applied
      // directly to an <a>, which would otherwise make active and
      // inactive items render in the exact same inherited color —
      // wrapping the icon+label in a span sidesteps that entirely.
      className={`group relative flex h-9 items-center rounded-control border px-3 text-sm font-medium no-underline transition-colors duration-150 ${
        active
          ? "border-accent/30 bg-accent-soft shadow-[0_0_0_1px_rgba(217,128,74,0.08)]"
          : "border-transparent hover:border-line hover:bg-surface"
      }`}
    >
      <span
        className={`flex flex-1 items-center gap-2.5 ${active ? "text-ink" : "text-ink-2 group-hover:text-ink"}`}
      >
        <Icon className={`shrink-0 ${active ? "text-accent" : ""}`} />
        <span className="flex-1 truncate">{item.label}</span>
      </span>
      {!!badge && badge > 0 && (
        <span className="flex h-4.5 min-w-4.5 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold text-accent-ink tabular-nums">
          {badge}
        </span>
      )}
    </Link>
  );
}

function Brand({ tagline = false }: { tagline?: boolean }) {
  return (
    <Link
      href="/home"
      className="flex items-center gap-2 px-1 py-1 text-sm font-semibold tracking-tight text-ink no-underline transition-opacity duration-150 hover:opacity-80"
    >
      <BrandMark className="text-accent" />
      <span>
        AgentOps AI
        {tagline && (
          <span className="mt-0.5 block text-[9px] font-medium tracking-[0.12em] text-ink-3 uppercase">
            Trusted agents. Real impact.
          </span>
        )}
      </span>
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
    <div className="flex items-center gap-2.5 rounded-control px-3 py-2">
      <span className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-sm font-semibold text-accent ring-1 ring-line-strong">
        {loading ? "" : initial}
        <span
          className="absolute right-0 bottom-0 h-2 w-2 rounded-full bg-success ring-2 ring-sidebar-bg"
          aria-hidden="true"
          title="Signed in"
        />
      </span>
      <div className="min-w-0">
        <p className="truncate text-xs font-medium text-ink">
          {loading ? "Loading…" : (email ?? "Signed in")}
        </p>
        <p className="text-[11px] text-ink-3">Signed in</p>
      </div>
    </div>
  );
}

function SidebarNav({
  pathname,
  navBadge,
  onNavigate,
}: {
  pathname: string;
  navBadge: (href: string) => number | undefined;
  onNavigate?: () => void;
}) {
  return (
    <nav className="relative flex flex-1 flex-col gap-0.5 overflow-y-auto">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.href}
          item={item}
          active={pathname.startsWith(item.href)}
          badge={navBadge(item.href)}
          onClick={onNavigate}
        />
      ))}
    </nav>
  );
}

/**
 * The authenticated application shell — a dark espresso sidebar (desktop)
 * + the dark "app canvas" content area (the `.app-canvas` scoped token
 * override in globals.css), used by every page behind login. Every page
 * keeps exactly the same data/mutation logic and only hands this
 * component its content plus an onLogout callback and an optional
 * breadcrumb.
 *
 * "Espresso Ink" (v2 redesign): the sidebar no longer draws from a
 * separate --shell-* token family shared with the pre-auth landing/auth
 * panels (those keep their own untouched brand identity) — it's a plain
 * child of `.app-canvas`, so it inherits that scope's ink/accent/surface
 * tokens directly via normal CSS cascade. Only its own background
 * (--sidebar-bg, "the same family, one step lifted") is a dedicated
 * token. This guarantees the sidebar and the app content can never
 * visually drift apart, and keeps the pre-auth pages completely
 * unaffected by anything changed here.
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
      <aside className="relative z-10 hidden w-64 shrink-0 flex-col overflow-hidden border-r border-line bg-sidebar-bg px-3 py-4 md:flex">
        {/* The sidebar's one retained decorative element: a single
            organic (asymmetric-radius) shape, very low opacity, anchored
            to the bottom corner only — the v2 brief's explicit allowance
            ("retain the organic pattern as a single <=5% element at the
            bottom only"), replacing v1's three high-opacity blurred
            blobs plus visible grid lines. */}
        <div
          className="pointer-events-none absolute -bottom-24 -left-16 h-72 w-64 opacity-[0.05]"
          style={{
            borderRadius: "58% 42% 66% 34% / 48% 40% 60% 52%",
            transform: "rotate(-8deg)",
            background: "var(--accent)",
          }}
          aria-hidden="true"
        />
        <Brand tagline />
        <div className="relative mt-7 flex flex-1 flex-col overflow-hidden">
          <SidebarNav pathname={pathname} navBadge={navBadge} />
        </div>
        <div className="relative flex flex-col gap-0.5 border-t border-line pt-2">
          <NavLink item={SETTINGS_ITEM} active={pathname.startsWith(SETTINGS_ITEM.href)} />
        </div>
        <div className="relative flex flex-col gap-2 border-t border-line pt-3">
          <UserBadge email={userQuery.data?.email} loading={userQuery.isLoading} />
          <button
            type="button"
            onClick={() => document.getElementById("global-search-input")?.focus()}
            className="flex w-full items-center gap-2.5 rounded-control border border-line px-3 py-2 text-left transition-colors duration-150 hover:border-line-strong hover:bg-surface"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-control bg-surface-2 text-ink-2">
              <SearchIcon />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs font-medium text-ink">
                Get started with Cmd + K
              </span>
              <span className="block truncate text-[11px] text-ink-3">
                Search agents, runs, tests…
              </span>
            </span>
          </button>
        </div>
      </aside>

      <div className="relative flex min-w-0 flex-1 flex-col">
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
              <Brand />
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
                <span className="hidden min-w-0 flex-col items-start leading-tight sm:flex">
                  <span className="max-w-32 truncate text-xs font-semibold text-ink">
                    {userQuery.isLoading
                      ? ""
                      : (userQuery.data?.full_name ?? userQuery.data?.email ?? "Signed in")}
                  </span>
                </span>
                <ChevronDownIcon
                  className={`text-ink-3 transition-transform duration-150 ${userMenuOpen ? "rotate-180" : ""}`}
                />
              </button>
              {userMenuOpen && (
                <div className="glass absolute top-full right-0 z-30 mt-2 w-44 overflow-hidden rounded-float border py-1 shadow-lg">
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
            className="absolute inset-0 bg-black/60"
            onClick={() => setMobileNavOpen(false)}
            aria-hidden="true"
          />
          <div className="animate-fade-in relative flex w-72 flex-col overflow-y-auto bg-sidebar-bg px-3 py-4 shadow-lg">
            <div className="flex items-center justify-between">
              <Brand />
              <button
                onClick={() => setMobileNavOpen(false)}
                className="text-ink-2 transition-colors duration-150 hover:text-ink"
                aria-label="Close navigation"
              >
                <CloseIcon />
              </button>
            </div>
            <div className="mt-6 flex flex-1 flex-col overflow-hidden">
              <SidebarNav
                pathname={pathname}
                navBadge={navBadge}
                onNavigate={() => setMobileNavOpen(false)}
              />
              <div className="mt-1 flex flex-col gap-0.5 border-t border-line pt-2">
                <NavLink
                  item={SETTINGS_ITEM}
                  active={pathname.startsWith(SETTINGS_ITEM.href)}
                  onClick={() => setMobileNavOpen(false)}
                />
              </div>
            </div>
            <div className="mt-auto flex flex-col gap-1 border-t border-line pt-3">
              <UserBadge email={userQuery.data?.email} loading={userQuery.isLoading} />
              <button
                onClick={onLogout}
                className="flex h-8 w-full items-center gap-2.5 rounded-control px-3 text-sm font-medium text-ink-2 transition-colors duration-150 hover:bg-surface-2 hover:text-ink"
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
