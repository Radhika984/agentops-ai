"use client";

import { useEffect, useSyncExternalStore } from "react";
import { useRouter } from "next/navigation";
import { getToken } from "./api";

function subscribe(callback: () => void): () => void {
  window.addEventListener("storage", callback);
  return () => window.removeEventListener("storage", callback);
}

function getSnapshot(): boolean {
  return Boolean(getToken());
}

// Used for both the server render and the client's first (hydration)
// render, so that first render is guaranteed identical on both sides —
// the actual, possibly-different client value from getSnapshot() is only
// applied in the corrective re-render React runs right after hydrating,
// never during hydration itself. A useState lazy initializer branching on
// `typeof window` cannot offer this guarantee: it would return `null`
// server-side but the real token value on the client's very first render,
// which is a genuine hydration mismatch, not just an effect-timing nicety.
function getServerSnapshot(): boolean {
  return false;
}

/**
 * Redirects to /login if no token is present. Returns whether the page is
 * clear to render its authenticated content.
 *
 * The redirect effect re-reads the token directly instead of depending on
 * `hasToken`, so it can never fire on the transient `false` that both
 * server and client start with — it only ever acts on the real client
 * value, once, on mount.
 */
export function useRequireAuth(): boolean {
  const router = useRouter();
  const hasToken = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
    }
  }, [router]);

  return hasToken;
}
