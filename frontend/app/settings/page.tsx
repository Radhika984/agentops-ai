"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AppShell } from "../components/AppShell";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Field, PasswordField } from "../components/ui/Input";
import { Skeleton } from "../components/ui/Skeleton";
import { SafetyIcon, SettingsIcon, WarningIcon } from "../components/ui/icons";
import {
  ApiError,
  changePassword,
  clearToken,
  createApiKey,
  getCurrentUser,
  getNotificationPreferences,
  listApiKeys,
  revokeApiKey,
  updateNotificationPreferences,
  updateProfile,
  type NotificationPreferences,
} from "../lib/api";
import { useRequireAuth } from "../lib/useRequireAuth";

type Tab = "profile" | "notifications" | "api-keys" | "security";
// `sensitive` drives the small SafetyIcon affordance in the tab bar —
// only the two tabs that can grant access (revocable API keys) or
// change the account's own credentials (password) are flagged, not
// every tab, so the signal stays meaningful.
const TABS: { id: Tab; label: string; sensitive?: boolean }[] = [
  { id: "profile", label: "Profile" },
  { id: "notifications", label: "Notification Preferences" },
  { id: "api-keys", label: "API Keys", sensitive: true },
  { id: "security", label: "Security", sensitive: true },
];

function ProfileTab() {
  const queryClient = useQueryClient();
  const userQuery = useQuery({ queryKey: ["me"], queryFn: getCurrentUser });
  const [fullName, setFullName] = useState("");
  // React's documented "adjust state during render" escape hatch
  // (https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes)
  // for "seed editable local state once server data arrives" — setting
  // state directly in an effect body is flagged by this project's
  // react-hooks/set-state-in-effect lint rule and causes an extra
  // render; this render-phase conditional setState is the recommended
  // alternative, not a workaround.
  const [seededFrom, setSeededFrom] = useState<typeof userQuery.data>(undefined);
  if (userQuery.data && userQuery.data !== seededFrom) {
    setSeededFrom(userQuery.data);
    setFullName(userQuery.data.full_name ?? "");
  }

  const mutation = useMutation({
    mutationFn: () => updateProfile(fullName.trim() || null),
    onSuccess: (user) => {
      queryClient.setQueryData(["me"], user);
    },
  });

  if (userQuery.isLoading) return <Skeleton className="h-40" />;

  return (
    <Card elevation="raised" className="max-w-lg">
      <form
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          mutation.mutate();
        }}
        className="flex flex-col gap-4"
      >
        <Field label="Email" value={userQuery.data?.email ?? ""} disabled readOnly />
        <Field
          label="Full name"
          value={fullName}
          onChange={(e) => setFullName(e.target.value)}
          placeholder="Your name"
        />
        <div>
          <Button type="submit" variant="primary" disabled={mutation.isPending}>
            {mutation.isPending ? "Saving…" : "Save profile"}
          </Button>
        </div>
        {mutation.isSuccess && <p className="text-sm text-success">Profile updated.</p>}
        {mutation.isError && (
          <p className="text-sm text-danger">
            {mutation.error instanceof ApiError ? mutation.error.message : "Could not save profile."}
          </p>
        )}
      </form>
    </Card>
  );
}

const NOTIFICATION_LABELS: { key: keyof NotificationPreferences; label: string; hint: string }[] = [
  {
    key: "notify_on_suite_run_complete",
    label: "Suite run completed",
    hint: "A test suite finished running.",
  },
  {
    key: "notify_on_release_gate",
    label: "Release gate evaluated",
    hint: "A release was held or passed.",
  },
  {
    key: "notify_on_autofix_proposed",
    label: "AutoFix proposed",
    hint: "A fix was proposed for a failing result.",
  },
  {
    key: "notify_on_approval_decided",
    label: "Approval decided",
    hint: "An approval was approved or rejected.",
  },
];

function NotificationsTab() {
  const prefsQuery = useQuery({
    queryKey: ["notification-preferences"],
    queryFn: getNotificationPreferences,
  });
  const [draft, setDraft] = useState<NotificationPreferences | null>(null);
  // Same render-phase seeding pattern as ProfileTab above — see its
  // comment for why this isn't a useEffect.
  const [seededFrom, setSeededFrom] = useState<typeof prefsQuery.data>(undefined);
  if (prefsQuery.data && prefsQuery.data !== seededFrom) {
    setSeededFrom(prefsQuery.data);
    setDraft(prefsQuery.data);
  }

  const mutation = useMutation({
    mutationFn: (prefs: NotificationPreferences) => updateNotificationPreferences(prefs),
    onSuccess: (prefs) => setDraft(prefs),
  });

  if (prefsQuery.isLoading || !draft) return <Skeleton className="h-56" />;

  return (
    <Card elevation="raised" className="max-w-lg">
      <p className="text-xs text-ink-3">
        Controls which real product events appear in your Recent Activity feed. This app has no
        email or push notifications — these preferences govern the one real delivery surface it
        has.
      </p>
      <div className="mt-4 flex flex-col gap-3">
        {NOTIFICATION_LABELS.map(({ key, label, hint }) => (
          <label
            key={key}
            className="flex cursor-pointer items-start gap-3 rounded-md border border-line px-3 py-2.5 transition-colors duration-150 hover:bg-surface-2"
          >
            <input
              type="checkbox"
              checked={draft[key]}
              onChange={(e) => setDraft({ ...draft, [key]: e.target.checked })}
              className="mt-0.5 h-4 w-4 accent-accent"
            />
            <span>
              <span className="block text-sm font-medium text-ink">{label}</span>
              <span className="block text-xs text-ink-3">{hint}</span>
            </span>
          </label>
        ))}
      </div>
      <div className="mt-4">
        <Button
          variant="primary"
          disabled={mutation.isPending}
          onClick={() => draft && mutation.mutate(draft)}
        >
          {mutation.isPending ? "Saving…" : "Save preferences"}
        </Button>
      </div>
      {mutation.isSuccess && <p className="mt-2 text-sm text-success">Preferences saved.</p>}
    </Card>
  );
}

function ApiKeysTab() {
  const queryClient = useQueryClient();
  const keysQuery = useQuery({ queryKey: ["api-keys"], queryFn: listApiKeys });
  const [name, setName] = useState("");
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  // UX-001: revoking a key is irreversible (no un-revoke/reactivate
  // endpoint exists) and previously fired on the first click with no
  // confirmation. Tracks which row is mid-confirmation, mirroring the
  // confirmingDelete pattern in test-suites/[suiteId]/page.tsx's
  // "Delete test case" flow.
  const [confirmingRevokeId, setConfirmingRevokeId] = useState<string | null>(null);

  const createMutation = useMutation({
    mutationFn: () => createApiKey(name.trim()),
    onSuccess: (created) => {
      setRevealedKey(created.api_key);
      setName("");
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: (keyId: string) => revokeApiKey(keyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
      setConfirmingRevokeId(null);
    },
  });

  return (
    <div className="flex max-w-2xl flex-col gap-5">
      <Card elevation="raised">
        <form
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            if (name.trim()) createMutation.mutate();
          }}
          className="flex flex-col gap-3 sm:flex-row sm:items-end"
        >
          <Field
            label="New API key name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. CI pipeline"
            className="flex-1"
          />
          <Button type="submit" variant="primary" disabled={createMutation.isPending || !name.trim()}>
            {createMutation.isPending ? "Creating…" : "+ Create key"}
          </Button>
        </form>
        {createMutation.isError && (
          <p className="mt-2 text-sm text-danger">
            {createMutation.error instanceof ApiError
              ? createMutation.error.message
              : "Could not create key."}
          </p>
        )}
      </Card>

      {revealedKey && (
        <Card elevation="glass" className="border-accent/30">
          <p className="flex items-center gap-1.5 text-sm font-semibold text-ink">
            <WarningIcon className="text-accent" />
            Your new API key — shown once
          </p>
          <p className="mt-1 text-xs text-ink-3">
            Copy it now — for security, it is shown only this once and can never be retrieved
            again.
          </p>
          <div className="mt-3 flex items-center gap-2">
            <code className="flex-1 overflow-x-auto rounded-md bg-surface-2 px-3 py-2 text-xs text-ink">
              {revealedKey}
            </code>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => navigator.clipboard?.writeText(revealedKey)}
            >
              Copy
            </Button>
          </div>
          <div className="mt-3">
            <Button variant="tertiary" size="sm" onClick={() => setRevealedKey(null)}>
              Done
            </Button>
          </div>
        </Card>
      )}

      <div>
        <h2 className="text-sm font-semibold text-ink">Your API keys</h2>
        <div className="mt-3">
          {keysQuery.isLoading && <Skeleton className="h-20" />}
          {keysQuery.data && keysQuery.data.length === 0 && (
            <EmptyState
              title="No API keys yet"
              description="Create one above to authenticate programmatic (CI) requests to the AgentOps API."
            />
          )}
          {keysQuery.data && keysQuery.data.length > 0 && (
            <div className="flex flex-col gap-2">
              {keysQuery.data.map((key) => {
                const isConfirming = confirmingRevokeId === key.id;
                const revokeFailed = revokeMutation.isError && revokeMutation.variables === key.id;
                return (
                  <Card key={key.id} elevation="flat" className="flex flex-col gap-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="truncate text-sm font-medium text-ink">{key.name}</p>
                          {key.revoked_at && <Badge tone="danger">revoked</Badge>}
                        </div>
                        <p className="mt-0.5 font-mono text-xs text-ink-3">{key.key_prefix}…</p>
                        <p className="mt-0.5 text-[11px] text-ink-3">
                          Created {new Date(key.created_at).toLocaleDateString()}
                          {key.last_used_at &&
                            ` · Last used ${new Date(key.last_used_at).toLocaleDateString()}`}
                        </p>
                      </div>
                      {!key.revoked_at && !isConfirming && (
                        <Button
                          variant="danger"
                          size="sm"
                          disabled={revokeMutation.isPending}
                          onClick={() => setConfirmingRevokeId(key.id)}
                        >
                          Revoke
                        </Button>
                      )}
                    </div>

                    {!key.revoked_at && isConfirming && (
                      <div className="flex flex-wrap items-center gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2.5">
                        <WarningIcon className="text-danger" />
                        <span className="text-xs text-danger">
                          Revoke &ldquo;{key.name}&rdquo;? This can&apos;t be undone.
                        </span>
                        <Button
                          variant="danger"
                          size="sm"
                          onClick={() => revokeMutation.mutate(key.id)}
                          disabled={revokeMutation.isPending}
                        >
                          {revokeMutation.isPending && revokeMutation.variables === key.id
                            ? "Revoking…"
                            : "Confirm revoke"}
                        </Button>
                        <Button
                          variant="tertiary"
                          size="sm"
                          onClick={() => setConfirmingRevokeId(null)}
                          disabled={revokeMutation.isPending}
                        >
                          Cancel
                        </Button>
                      </div>
                    )}

                    {revokeFailed && (
                      <p className="text-xs text-danger">
                        {revokeMutation.error instanceof ApiError
                          ? revokeMutation.error.message
                          : "Could not revoke this key."}
                      </p>
                    )}
                  </Card>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SecurityTab() {
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => changePassword(currentPassword, newPassword),
    onSuccess: () => {
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setLocalError(null);
    if (newPassword.length < 8) {
      setLocalError("New password must be at least 8 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setLocalError("New password and confirmation do not match.");
      return;
    }
    mutation.mutate();
  }

  return (
    <Card elevation="raised" className="max-w-lg">
      <p className="flex items-start gap-2 rounded-md border border-line bg-surface-2 px-3 py-2.5 text-xs text-ink-2">
        <WarningIcon className="mt-0.5 shrink-0 text-ink-3" />
        This app authenticates with a JWT bearer token issued at login. Changing your password
        here immediately invalidates it for any future login attempt.
      </p>
      <form onSubmit={handleSubmit} className="mt-4 flex flex-col gap-4">
        <PasswordField
          label="Current password"
          value={currentPassword}
          onChange={(e) => setCurrentPassword(e.target.value)}
          autoComplete="current-password"
        />
        <PasswordField
          label="New password"
          value={newPassword}
          onChange={(e) => setNewPassword(e.target.value)}
          autoComplete="new-password"
        />
        <PasswordField
          label="Confirm new password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
          autoComplete="new-password"
        />
        <div>
          <Button type="submit" variant="primary" disabled={mutation.isPending}>
            {mutation.isPending ? "Updating…" : "Change password"}
          </Button>
        </div>
        {mutation.isSuccess && <p className="text-sm text-success">Password updated.</p>}
        {(localError || mutation.isError) && (
          <p className="text-sm text-danger">
            {localError ??
              (mutation.error instanceof ApiError
                ? mutation.error.message
                : "Could not change password.")}
          </p>
        )}
      </form>
    </Card>
  );
}

export default function SettingsPage() {
  const router = useRouter();
  const checkedAuth = useRequireAuth();
  const [tab, setTab] = useState<Tab>("profile");

  function handleLogout() {
    clearToken();
    router.replace("/login");
  }

  if (!checkedAuth) return null;

  return (
    <AppShell onLogout={handleLogout}>
      <div className="animate-fade-in-up mx-auto w-full max-w-5xl px-4 py-7 md:px-8">
        <div className="flex items-center gap-2.5">
          <span className="flex h-9 w-9 items-center justify-center rounded-md bg-accent-soft text-accent">
            <SettingsIcon />
          </span>
          <h1 className="text-3xl font-bold tracking-tight text-ink">Settings</h1>
        </div>

        {/* overflow-y-hidden is deliberate, not decorative: setting only
            overflow-x-auto leaves overflow-y at its default, and per the
            CSS Overflow spec a non-visible x-axis forces the y-axis to
            also resolve to auto — so any content even 1px taller than
            this row (the sensitive-tab SafetyIcon included) was enough
            to spawn a stray vertical scrollbar affordance next to a row
            that was never meant to scroll vertically at all.
            py-1.5 is load-bearing, not spacing polish: a keyboard focus
            ring needs outline-width(2px) + outline-offset(2px) = 4px of
            clearance beyond a button's own box on every side. Without
            this padding the container's height matched the buttons'
            height almost exactly, so overflow-y-hidden silently clipped
            the top/bottom of every tab's focus ring — found by actually
            tabbing to a tab and measuring the rendered outline's real
            clearance (getBoundingClientRect on both the focused button
            and its container), not assumed. 6px of padding leaves
            comfortable headroom above the 4px the ring actually needs. */}
        <div className="mt-5 flex items-center gap-1 overflow-x-auto overflow-y-hidden border-b border-line py-1.5">
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`relative flex shrink-0 items-center gap-1.5 rounded-t-md px-3.5 py-2 text-sm font-medium whitespace-nowrap transition-colors duration-150 ${
                tab === t.id ? "bg-surface-2 text-ink" : "text-ink-3 hover:text-ink-2"
              }`}
            >
              {t.sensitive && <SafetyIcon className={tab === t.id ? "text-accent" : "text-ink-3"} width={14} height={14} />}
              {t.label}
              {tab === t.id && (
                <span className="absolute right-0 -bottom-px left-0 h-0.5 rounded-full bg-accent" />
              )}
            </button>
          ))}
        </div>

        <div className="mt-6">
          {tab === "profile" && <ProfileTab />}
          {tab === "notifications" && <NotificationsTab />}
          {tab === "api-keys" && <ApiKeysTab />}
          {tab === "security" && <SecurityTab />}
        </div>
      </div>
    </AppShell>
  );
}
