import type { HTMLAttributes, ReactNode } from "react";

type Elevation = "flat" | "raised" | "glass";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  padded?: boolean;
  /** flat: everyday grouping (default). raised: brighter surface + a
   * touch more shadow, for the one or two things per screen that should
   * visibly sit above the rest. glass: the restrained translucent
   * treatment, reserved for genuinely important floating/status panels
   * (see .glass in globals.css) — never used for ordinary cards. */
  elevation?: Elevation;
  /** A single, restrained warm corner glow (bottom-right), baked into the
   * card's own `background-image` — see `.card-depth` in globals.css —
   * so every "raised"/"glass" card across the app shares one consistent
   * depth treatment without each page hand-rolling its own decoration.
   * Deliberately never applied to "flat" (dense, everyday grouping,
   * where it would be noise) and off by default there; defaults to on
   * for "raised"/"glass". Pass `false` to opt out for a card that
   * already carries its own bespoke corner decoration (e.g. Home's
   * per-tone stat tiles), so the two glows never stack. Implemented as a
   * background-image (not an overlay element) specifically so it never
   * needs `overflow-hidden` on the card — it can't leak past the
   * card's own border-radius, and never risks clipping a dropdown or
   * tooltip that needs to render outside the card's bounds. */
  atmosphere?: boolean;
}

// Each level pairs a translucency (bg-surface/-elevated, or the .glass
// recipe) with a matching backdrop-blur — the actual mechanism that
// makes a translucent surface read as frosted glass rather than a
// slightly-darker flat box. On the light theme these surfaces are
// effectively opaque, so the blur is simply inert there (nothing to
// blur); on the dark `.app-canvas` theme (globals.css) the same three
// surface tokens are genuinely translucent, so the blur becomes visible
// and every elevation level — not just `elevation="glass"` — shows real
// depth against the ambient canvas behind it.
const elevationClasses: Record<Elevation, string> = {
  flat: "border-line bg-surface shadow-sm backdrop-blur-md",
  raised: "border-line-strong bg-surface-elevated shadow-md backdrop-blur-lg",
  glass: "glass shadow-md",
};

/** A single, restrained elevation system reused everywhere a group of
 * content needs visual separation from the page — not used for every
 * element, only real groupings (see each page for where it's applied). */
export function Card({
  children,
  padded = true,
  elevation = "flat",
  atmosphere,
  className = "",
  ...props
}: CardProps) {
  const showAtmosphere = atmosphere ?? elevation !== "flat";
  return (
    <div
      className={`rounded-lg border ${elevationClasses[elevation]} ${showAtmosphere ? "card-depth" : ""} ${padded ? "p-4" : ""} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
