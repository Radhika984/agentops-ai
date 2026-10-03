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
}

// Each level is a solid, opaque layered surface — depth comes from the
// surface tone itself, a hairline border, and the inset top highlight
// baked into --shadow-sm/md/lg (see globals.css), never from a glow or
// blur. `.glass` (genuinely floating layers only — header, dropdowns,
// the mobile nav drawer) is the one exception that stays translucent.
const elevationClasses: Record<Elevation, string> = {
  flat: "border-line bg-surface shadow-sm",
  raised: "border-line-strong bg-surface-elevated shadow-md",
  glass: "glass shadow-md",
};

/** A single, restrained elevation system reused everywhere a group of
 * content needs visual separation from the page — not used for every
 * element, only real groupings (see each page for where it's applied). */
export function Card({
  children,
  padded = true,
  elevation = "flat",
  className = "",
  ...props
}: CardProps) {
  return (
    <div
      className={`rounded-surface border ${elevationClasses[elevation]} ${padded ? "p-4" : ""} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}
