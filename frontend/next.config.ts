import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Prevents `next dev` from regenerating AGENTS.md/CLAUDE.md on every
  // start — unrelated to the blueprint, pure tooling noise.
  agentRules: false,
  // Hides the floating dev-mode indicator badge ("N" in the corner) —
  // pure dev-tooling chrome, not part of the application UI. Documented
  // Next.js config, not a functional change; only affects `next dev`
  // (this project's Docker command), never a production `next build`.
  devIndicators: false,
};

export default nextConfig;
