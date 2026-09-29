import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { shouldRetry } from "./queryClient";

// BUG-004: react-query's own default (`retry: 3`) retried a deterministic
// 403 (Account B requesting Account A's agent) exactly like a flaky
// network blip — 4 attempts per query, 3 queries, ~12 requests, ~7s of
// backoff before the page ever settled into an error state. shouldRetry()
// is the fix: it must treat every 4xx as terminal (no retry) while
// leaving 5xx/network-error retry behavior exactly as react-query's own
// default did before.
describe("shouldRetry", () => {
  it("does not retry a 403 (unauthorized) response", () => {
    expect(shouldRetry(1, new ApiError(403, "Not authorized for this resource"))).toBe(false);
  });

  it("does not retry a 404 (not found) response", () => {
    expect(shouldRetry(1, new ApiError(404, "Agent not found"))).toBe(false);
  });

  it("does not retry a 401 (session expired) response", () => {
    // 401 is additionally handled by request() itself (clear token +
    // redirect to /login) — it must never be retried either.
    expect(shouldRetry(1, new ApiError(401, "Not authenticated"))).toBe(false);
  });

  it("does not retry any 4xx response", () => {
    expect(shouldRetry(1, new ApiError(422, "Unprocessable"))).toBe(false);
    expect(shouldRetry(1, new ApiError(409, "Conflict"))).toBe(false);
  });

  it("still retries a 5xx response up to 3 times, matching the prior default", () => {
    const err = new ApiError(500, "Internal Server Error");
    expect(shouldRetry(1, err)).toBe(true);
    expect(shouldRetry(2, err)).toBe(true);
    expect(shouldRetry(3, err)).toBe(false);
  });

  it("still retries a plain network error (not an ApiError) up to 3 times", () => {
    const err = new TypeError("Failed to fetch");
    expect(shouldRetry(1, err)).toBe(true);
    expect(shouldRetry(3, err)).toBe(false);
  });
});
