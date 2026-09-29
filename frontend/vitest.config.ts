import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// BUG-004: the project had no frontend test runner at all before this
// fix — this is the minimal standard setup (Vitest + jsdom + React
// Testing Library) needed to add the focused regression tests the task
// requires, not a general test-infrastructure rollout. Scoped to
// app/**/*.test.tsx only.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["app/**/*.test.{ts,tsx}"],
  },
});
