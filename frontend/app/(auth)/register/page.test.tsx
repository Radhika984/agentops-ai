import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const nav = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => nav,
}));

const api = vi.hoisted(() => ({
  register: vi.fn(),
  login: vi.fn(),
  setToken: vi.fn(),
}));
vi.mock("../../lib/api", async () => {
  const actual = await vi.importActual<typeof import("../../lib/api")>("../../lib/api");
  return { ...actual, ...api };
});

import { ApiError } from "../../lib/api";
import RegisterPage from "./page";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RegisterPage />
    </QueryClientProvider>,
  );
}

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText("Email address"), {
    target: { value: "new-user@example.com" },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: "Password123!" },
  });
  fireEvent.click(screen.getByRole("button", { name: /create account/i }));
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  cleanup();
});

describe("RegisterPage — BUG-001", () => {
  it("successful registration still logs the new user in and redirects to /home", async () => {
    api.register.mockResolvedValue({ id: "u1", email: "new-user@example.com" });
    api.login.mockResolvedValue({ access_token: "tok-123", token_type: "bearer" });

    renderPage();
    fillAndSubmit();

    await vi.waitFor(() => expect(api.setToken).toHaveBeenCalledWith("tok-123"));
    expect(api.register).toHaveBeenCalledWith("new-user@example.com", "Password123!", "");
    expect(api.login).toHaveBeenCalledWith("new-user@example.com", "Password123!");
    expect(nav.push).toHaveBeenCalledWith("/home");
  });

  it("a 422 with a backend-derived validation message displays that real message", async () => {
    api.register.mockRejectedValue(
      new ApiError(
        422,
        "value is not a valid email address: The part after the @-sign is a special-use or reserved name that cannot be used with email.",
      ),
    );

    renderPage();
    fillAndSubmit();

    expect(
      await screen.findByText(
        "value is not a valid email address: The part after the @-sign is a special-use or reserved name that cannot be used with email.",
      ),
    ).toBeInTheDocument();
  });

  it("does not show the raw generic 'Unprocessable Entity' message when a real detail exists", async () => {
    api.register.mockRejectedValue(new ApiError(422, "value is not a valid email address: reserved domain."));

    renderPage();
    fillAndSubmit();

    await screen.findByText("value is not a valid email address: reserved domain.");
    expect(screen.queryByText("Unprocessable Entity")).not.toBeInTheDocument();
  });

  it("a 5xx server error still shows the backend's fallback message (unaffected by this fix)", async () => {
    api.register.mockRejectedValue(new ApiError(500, "Internal Server Error"));

    renderPage();
    fillAndSubmit();

    expect(await screen.findByText("Internal Server Error")).toBeInTheDocument();
  });

  it("a non-ApiError failure (e.g. a network error) still uses the generic fallback message", async () => {
    api.register.mockRejectedValue(new TypeError("Failed to fetch"));

    renderPage();
    fillAndSubmit();

    expect(await screen.findByText("Something went wrong. Please try again.")).toBeInTheDocument();
  });
});
