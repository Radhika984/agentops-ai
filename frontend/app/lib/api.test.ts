import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, extractErrorDetail, getCurrentUser, register } from "./api";

// BUG-001: FastAPI's own request-validation layer (e.g. UserCreate.email:
// EmailStr rejecting a reserved-TLD address) returns `{"detail": [{"loc":
// ..., "msg": "...", "type": "..."}]}`, not the plain `{"detail":
// "<string>"}` shape every route-handler-raised domain error uses.
// extractErrorDetail() is the fix: read the real message out of either
// shape instead of silently falling through to res.statusText
// ("Unprocessable Entity").
describe("extractErrorDetail", () => {
  it("reads a plain string detail (route-handler-raised domain errors)", () => {
    expect(extractErrorDetail({ detail: "Email already registered" })).toBe(
      "Email already registered",
    );
  });

  it("reads the real message out of FastAPI's array-of-validation-errors shape", () => {
    const data = {
      detail: [
        {
          type: "value_error",
          loc: ["body", "email"],
          msg: "value is not a valid email address: The part after the @-sign is a special-use or reserved name that cannot be used with email.",
          input: "bug001-test@local.test",
        },
      ],
    };
    expect(extractErrorDetail(data)).toBe(
      "value is not a valid email address: The part after the @-sign is a special-use or reserved name that cannot be used with email.",
    );
  });

  it("joins multiple simultaneous validation errors into one readable message", () => {
    const data = {
      detail: [
        { type: "value_error", loc: ["body", "email"], msg: "value is not a valid email address: reserved domain." },
        { type: "string_too_short", loc: ["body", "password"], msg: "String should have at least 8 characters" },
      ],
    };
    expect(extractErrorDetail(data)).toBe(
      "value is not a valid email address: reserved domain.; String should have at least 8 characters",
    );
  });

  it("returns null (caller falls back to statusText) for a malformed/empty body", () => {
    expect(extractErrorDetail({})).toBeNull();
    expect(extractErrorDetail(null)).toBeNull();
    expect(extractErrorDetail({ detail: [] })).toBeNull();
    expect(extractErrorDetail({ detail: [{ loc: ["body"] }] })).toBeNull();
    expect(extractErrorDetail({ detail: 42 })).toBeNull();
  });
});

const originalFetch = global.fetch;

describe("request() — end-to-end error handling through register()/getCurrentUser()", () => {
  beforeEach(() => {
    global.fetch = vi.fn();
  });

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("a 422 with FastAPI's array-shaped detail surfaces the real validation message, not 'Unprocessable Entity'", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: async () => ({
        detail: [
          {
            type: "value_error",
            loc: ["body", "email"],
            msg: "value is not a valid email address: The part after the @-sign is a special-use or reserved name that cannot be used with email.",
          },
        ],
      }),
    });

    await expect(register("bug001-test@local.test", "Password123!", undefined)).rejects.toMatchObject({
      status: 422,
      message: "value is not a valid email address: The part after the @-sign is a special-use or reserved name that cannot be used with email.",
    });
  });

  it("a 409 with a plain string detail (unrelated existing behavior) is unaffected", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({ detail: "Email already registered" }),
    });

    await expect(register("dup@example.com", "Password123!", undefined)).rejects.toMatchObject({
      status: 409,
      message: "Email already registered",
    });
  });

  it("a 500 with no usable JSON body falls back to statusText, same as before this fix", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
      json: async () => {
        throw new SyntaxError("Unexpected end of JSON input");
      },
    });

    await expect(getCurrentUser()).rejects.toMatchObject({
      status: 500,
      message: "Internal Server Error",
    });
  });

  it("a network failure (fetch itself rejects) propagates as a plain error, not a swallowed ApiError", async () => {
    (global.fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(getCurrentUser()).rejects.toThrow("Failed to fetch");
    await expect(getCurrentUser()).rejects.not.toBeInstanceOf(ApiError);
  });
});
