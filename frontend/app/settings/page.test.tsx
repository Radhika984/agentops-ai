import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/useRequireAuth", () => ({
  useRequireAuth: () => true,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/settings",
}));

const api = vi.hoisted(() => ({
  getCurrentUser: vi.fn(),
  listApprovals: vi.fn(),
  search: vi.fn(),
  clearToken: vi.fn(),
  listApiKeys: vi.fn(),
  createApiKey: vi.fn(),
  revokeApiKey: vi.fn(),
  getNotificationPreferences: vi.fn(),
}));

vi.mock("../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../lib/api")>("../lib/api");
  return { ...actual, ...api };
});

import { ApiError } from "../lib/api";
import SettingsPage from "./page";

const ACTIVE_KEY = {
  id: "key-1",
  name: "CI pipeline",
  key_prefix: "aops_abc123",
  last_used_at: null,
  revoked_at: null,
  created_at: "2026-01-01T00:00:00Z",
};

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SettingsPage />
    </QueryClientProvider>,
  );
}

async function openApiKeysTab() {
  fireEvent.click(await screen.findByRole("button", { name: "API Keys" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  api.getCurrentUser.mockResolvedValue({
    id: "u1",
    email: "owner@example.com",
    full_name: null,
    is_active: true,
    notify_on_suite_run_complete: true,
    notify_on_release_gate: true,
    notify_on_autofix_proposed: true,
    notify_on_approval_decided: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  });
  api.listApprovals.mockResolvedValue([]);
  api.search.mockResolvedValue({ results: [] });
  api.getNotificationPreferences.mockResolvedValue({
    notify_on_suite_run_complete: true,
    notify_on_release_gate: true,
    notify_on_autofix_proposed: true,
    notify_on_approval_decided: true,
  });
});

afterEach(() => {
  cleanup();
});

describe("Settings — ApiKeysTab — UX-001 revoke confirmation", () => {
  it("clicking Revoke does not call revokeApiKey", async () => {
    api.listApiKeys.mockResolvedValue([ACTIVE_KEY]);
    renderPage();
    await openApiKeysTab();

    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));

    expect(api.revokeApiKey).not.toHaveBeenCalled();
  });

  it("clicking Revoke shows the confirmation state", async () => {
    api.listApiKeys.mockResolvedValue([ACTIVE_KEY]);
    renderPage();
    await openApiKeysTab();

    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));

    expect(await screen.findByText(/This can't be undone/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm revoke" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("clicking Cancel hides the confirmation state and does not call revokeApiKey", async () => {
    api.listApiKeys.mockResolvedValue([ACTIVE_KEY]);
    renderPage();
    await openApiKeysTab();

    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    await screen.findByRole("button", { name: "Confirm revoke" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByText(/This can't be undone/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Revoke" })).toBeInTheDocument();
    expect(api.revokeApiKey).not.toHaveBeenCalled();
  });

  it("clicking Confirm revoke calls revokeApiKey exactly once with the correct key id, and disables during the request", async () => {
    let resolveRevoke: () => void;
    api.listApiKeys.mockResolvedValue([ACTIVE_KEY]);
    api.revokeApiKey.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveRevoke = resolve;
      }),
    );
    renderPage();
    await openApiKeysTab();

    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    const confirmButton = await screen.findByRole("button", { name: "Confirm revoke" });
    fireEvent.click(confirmButton);

    expect(await screen.findByRole("button", { name: "Revoking…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(api.revokeApiKey).toHaveBeenCalledTimes(1);
    expect(api.revokeApiKey).toHaveBeenCalledWith("key-1");

    resolveRevoke!();
  });

  it("a successful revoke updates the list to show the revoked state via the existing invalidation flow", async () => {
    api.listApiKeys.mockResolvedValueOnce([ACTIVE_KEY]).mockResolvedValue([
      { ...ACTIVE_KEY, revoked_at: "2026-01-02T00:00:00Z" },
    ]);
    api.revokeApiKey.mockResolvedValue(undefined);
    renderPage();
    await openApiKeysTab();

    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm revoke" }));

    expect(await screen.findByText("revoked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm revoke" })).not.toBeInTheDocument();
  });

  it("a failed revoke displays a visible, useful error message instead of failing silently", async () => {
    api.listApiKeys.mockResolvedValue([ACTIVE_KEY]);
    api.revokeApiKey.mockRejectedValue(new ApiError(500, "Could not revoke key: internal error"));
    renderPage();
    await openApiKeysTab();

    fireEvent.click(await screen.findByRole("button", { name: "Revoke" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm revoke" }));

    expect(await screen.findByText("Could not revoke key: internal error")).toBeInTheDocument();
    // The user can retry — the confirm step is still there, not reverted
    // all the way back to a bare, unconfirmed "Revoke".
    expect(screen.getByRole("button", { name: "Confirm revoke" })).toBeInTheDocument();
  });

  it("existing API-key creation behavior is unaffected", async () => {
    api.listApiKeys.mockResolvedValue([]);
    api.createApiKey.mockResolvedValue({
      id: "key-2",
      name: "New key",
      key_prefix: "aops_xyz",
      api_key: "aops_xyz_secret",
      created_at: "2026-01-01T00:00:00Z",
    });
    renderPage();
    await openApiKeysTab();

    fireEvent.change(screen.getByPlaceholderText("e.g. CI pipeline"), {
      target: { value: "New key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "+ Create key" }));

    expect(await screen.findByText("Your new API key — shown once")).toBeInTheDocument();
    expect(screen.getByText("aops_xyz_secret")).toBeInTheDocument();
    expect(api.createApiKey).toHaveBeenCalledWith("New key");
  });
});
