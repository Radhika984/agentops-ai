"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { ApiError } from "./api";

// BUG-004: react-query's own default (`retry: 3`) doesn't look at the
// error at all — it retried a 403 (a deterministic "you will never be
// authorized for this by retrying" result) exactly like a flaky network
// blip, firing every failing query 4 times before settling. A 4xx from
// the API is never fixed by retrying with the same token against the
// same resource (401 is already handled separately, one level down in
// api.ts's request(), by clearing the token and redirecting); 5xx/network
// errors are the only case retrying can plausibly help with, so those
// keep the previous 3-retry behavior unchanged.
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
    return false;
  }
  return failureCount < 3;
}

export function QueryProvider({ children }: { children: ReactNode }) {
  // Created inside the component (not module scope) so each browser tab
  // gets its own cache instead of sharing one across server-rendered requests.
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: shouldRetry },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
