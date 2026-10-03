"use client";

/**
 * The AgentOps AI "Intelligence Field" — the signup page's one signature
 * visual. An abstract geometric core (never a circle/hex/brain/chat icon)
 * with an asymmetric network of curved paths, nodes and traveling signal
 * particles around it. Pure SVG + CSS (keyframes defined in globals.css,
 * prefixed `signup-`, scoped under `.signup-canvas`) — no animation
 * library, no canvas/WebGL.
 *
 * Interactive, not just decorative: `focusField`/`passwordValid`/
 * `ctaActive` let the register page tell the field what the visitor is
 * doing, so the system visibly responds to the form next to it.
 */

type FocusTarget = "name" | "email" | "password" | null;

interface SignupFieldProps {
  focusField: FocusTarget;
  passwordValid: boolean;
  ctaActive: boolean;
  className?: string;
}

// Hand-placed, asymmetric node coordinates (viewBox 0 0 1200 900) — no
// node sits at a "nice" round distance from the core and no two edges run
// parallel, so the structure reads as organic rather than a generated
// star graph.
const CORE = { x: 540, y: 430 };

const NODES = [
  { id: "n1", x: 860, y: 150, r: 4, depth: "far" as const },
  { id: "n2", x: 1010, y: 330, r: 6, depth: "mid" as const },
  { id: "n3", x: 700, y: 95, r: 3.5, depth: "far" as const },
  { id: "n4", x: 300, y: 205, r: 5.5, depth: "mid" as const },
  { id: "n5", x: 140, y: 470, r: 7, depth: "near" as const },
  { id: "n6", x: 255, y: 700, r: 4.5, depth: "mid" as const },
  { id: "n7", x: 575, y: 790, r: 5, depth: "mid" as const },
  { id: "n8", x: 930, y: 660, r: 6.5, depth: "near" as const },
];

// Curved (never straight) core→node paths — each control point is offset
// unevenly so every arc bends a different amount and a different way.
const coreCurve = (nx: number, ny: number, bend: number) => {
  const mx = (CORE.x + nx) / 2 + bend;
  const my = (CORE.y + ny) / 2 - bend * 0.6;
  return `M ${CORE.x} ${CORE.y} Q ${mx} ${my} ${nx} ${ny}`;
};

const PATHS = [
  { id: "p1", d: coreCurve(860, 150, 40), dur: 6 },
  { id: "p2", d: coreCurve(1010, 330, -30), dur: 9 },
  { id: "p3", d: coreCurve(700, 95, 20), dur: 4 },
  { id: "p4", d: coreCurve(300, 205, -50), dur: 11 },
  { id: "p5", d: coreCurve(140, 470, 60), dur: 6 },
  { id: "p6", d: coreCurve(255, 700, -25), dur: 9 },
  { id: "p7", d: coreCurve(575, 790, 35), dur: 4 },
  { id: "p8", d: coreCurve(930, 660, -40), dur: 11 },
];

// A couple of node-to-node links so the structure reads as a network, not
// a pure star radiating from the core.
const CROSS_LINKS = [
  { id: "x1", d: `M 860 150 Q 950 230 1010 330` },
  { id: "x2", d: `M 140 470 Q 190 600 255 700` },
];

const PARTICLES = [
  { path: "p1", color: "var(--signup-violet)", dur: 7.5 },
  { path: "p4", color: "var(--signup-blue)", dur: 9.5 },
  { path: "p5", color: "var(--signup-cyan)", dur: 8 },
  { path: "p8", color: "var(--signup-violet)", dur: 10.5 },
];

export function SignupField({ focusField, passwordValid, ctaActive, className = "" }: SignupFieldProps) {
  return (
    <svg
      viewBox="0 0 1200 900"
      preserveAspectRatio="xMidYMid slice"
      className={`signup-field ${ctaActive ? "is-energized" : ""} ${className}`}
      role="presentation"
      aria-hidden="true"
    >
      <defs>
        <radialGradient id="sfAmbient1" cx="30%" cy="28%" r="55%">
          <stop offset="0%" stopColor="#6D28D9" stopOpacity="0.16" />
          <stop offset="100%" stopColor="#6D28D9" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="sfAmbient2" cx="78%" cy="68%" r="50%">
          <stop offset="0%" stopColor="#06B6D4" stopOpacity="0.1" />
          <stop offset="100%" stopColor="#06B6D4" stopOpacity="0" />
        </radialGradient>
        <radialGradient id="sfCoreGlow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#8B5CF6" stopOpacity="0.55" />
          <stop offset="55%" stopColor="#3B82F6" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#3B82F6" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="sfPathGrad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#8B5CF6" stopOpacity="0.55" />
          <stop offset="50%" stopColor="#3B82F6" stopOpacity="0.4" />
          <stop offset="100%" stopColor="#06B6D4" stopOpacity="0.3" />
        </linearGradient>
        <linearGradient id="sfShard1" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#A78BFA" />
          <stop offset="100%" stopColor="#6D28D9" />
        </linearGradient>
        <linearGradient id="sfShard2" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#60A5FA" />
          <stop offset="100%" stopColor="#2563EB" />
        </linearGradient>
        <linearGradient id="sfShard3" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#22D3EE" />
          <stop offset="100%" stopColor="#0E7490" />
        </linearGradient>
        <filter id="sfSoftBlur" x="-50%" y="-50%" width="200%" height="200%">
          <feGaussianBlur stdDeviation="46" />
        </filter>
        <filter id="sfGlowSmall" x="-200%" y="-200%" width="500%" height="500%">
          <feGaussianBlur stdDeviation="5" />
        </filter>
      </defs>

      {/* Layer 1 — ambient field: two unevenly-placed soft light pools, barely moving */}
      <g className="signup-ambient" filter="url(#sfSoftBlur)">
        <circle cx="340" cy="250" r="340" fill="url(#sfAmbient1)" />
        <circle cx="940" cy="620" r="300" fill="url(#sfAmbient2)" />
      </g>

      {/* Layer 2 — network paths (layer under nodes/core) */}
      <g fill="none" stroke="url(#sfPathGrad)" strokeLinecap="round">
        {PATHS.map((p) => (
          <path
            key={p.id}
            d={p.d}
            strokeWidth={1}
            strokeDasharray="2 10"
            className={`signup-path ${p.id === "p1" || p.id === "p3" ? "hidden lg:block" : ""}`}
            style={{ animationDuration: `${p.dur}s` }}
          />
        ))}
        {CROSS_LINKS.map((l) => (
          <path key={l.id} d={l.d} strokeWidth={0.75} strokeDasharray="1 14" opacity={0.35} className="hidden lg:block" />
        ))}
      </g>

      {/* Layer 4 — nodes, varied sizes/shapes, independent breathing rhythm */}
      <g>
        {NODES.map((n, i) => {
          const isPasswordNode = n.id === "n5";
          const lit = isPasswordNode && passwordValid;
          return (
            <g
              key={n.id}
              className={`signup-node ${n.depth === "far" ? "hidden lg:block" : ""}`}
              style={{ animationDuration: `${7 + i * 0.6}s`, animationDelay: `${i * 0.35}s` }}
              filter="url(#sfGlowSmall)"
            >
              {i % 3 === 0 ? (
                <rect
                  x={n.x - n.r}
                  y={n.y - n.r}
                  width={n.r * 2}
                  height={n.r * 2}
                  rx={1.2}
                  transform={`rotate(45 ${n.x} ${n.y})`}
                  fill={lit ? "#22D3EE" : "#A78BFA"}
                  opacity={n.depth === "far" ? 0.45 : n.depth === "mid" ? 0.7 : 0.9}
                />
              ) : (
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={n.r}
                  fill={lit ? "#22D3EE" : n.id === "n8" ? "#3B82F6" : "#8B5CF6"}
                  opacity={n.depth === "far" ? 0.45 : n.depth === "mid" ? 0.7 : 0.9}
                />
              )}
              {lit && (
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={n.r}
                  fill="none"
                  stroke="#22D3EE"
                  strokeWidth={1}
                  className="signup-ring"
                />
              )}
            </g>
          );
        })}
      </g>

      {/* Layer 5 — data particles traveling the network */}
      {PARTICLES.map((pt, i) => {
        const pathDef = PATHS.find((p) => p.id === pt.path)!;
        const mobileHidden = pt.path === "p1" || pt.path === "p8";
        return (
          <circle
            key={`particle-${pt.path}-${i}`}
            r={2.2}
            fill={pt.color}
            className={`signup-particle ${mobileHidden ? "hidden lg:block" : ""}`}
            style={{
              offsetPath: `path("${pathDef.d}")`,
              animationDuration: `${pt.dur}s, ${pt.dur * 0.82}s`,
              animationDelay: `${i * 1.3}s, ${i * 1.1}s`,
            }}
          />
        );
      })}

      {/* Email-focus response: a brighter signal that only travels while
          the email field is focused — the network visibly "listening". */}
      {focusField === "email" && (
        <circle
          r={3}
          fill="#F8FAFC"
          className="signup-particle signup-particle-active"
          style={{ offsetPath: `path("${PATHS[1].d}")` }}
        />
      )}
      {focusField === "name" && (
        <circle
          r={2.6}
          fill="#8B5CF6"
          className="signup-particle signup-particle-active"
          style={{ offsetPath: `path("${PATHS[2].d}")` }}
        />
      )}

      {/* Layer 6 — core: an abstract faceted shard cluster, not a circle/orb/hex/brain */}
      <g transform={`translate(${CORE.x} ${CORE.y})`}>
        <circle r={95} fill="url(#sfCoreGlow)" className="signup-core-glow" />
        <g className="signup-core-rotate">
          <g className="signup-core-breathe">
            <rect x={-7} y={-34} width={14} height={48} rx={6} fill="url(#sfShard1)" transform="rotate(0)" />
            <rect x={-7} y={-34} width={14} height={48} rx={6} fill="url(#sfShard2)" transform="rotate(120)" />
            <rect x={-7} y={-34} width={14} height={48} rx={6} fill="url(#sfShard3)" transform="rotate(240)" />
            <circle r={6} fill="#F8FAFC" />
          </g>
        </g>
      </g>
    </svg>
  );
}
