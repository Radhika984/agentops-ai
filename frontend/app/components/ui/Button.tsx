import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "secondary" | "tertiary" | "success" | "danger";
type Size = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const base =
  "inline-flex items-center justify-center gap-1.5 rounded-control font-medium transition-all duration-150 hover:-translate-y-px active:translate-y-0 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-45 disabled:hover:translate-y-0 disabled:active:scale-100";

const variants: Record<Variant, string> = {
  // The hover shadow uses a fixed warm-accent color (not var(--accent)),
  // deliberately: this is a glow, not an elevation shadow, and should
  // read the same on both the light and dark `.app-canvas` themes rather
  // than shifting with --shadow-color/--accent overrides.
  primary:
    "bg-accent text-accent-ink shadow-sm hover:bg-accent-hover hover:shadow-[0_6px_20px_-4px_rgba(224,138,99,0.45)]",
  secondary: "border border-line-strong bg-surface text-ink backdrop-blur-md hover:bg-surface-2",
  tertiary: "text-accent hover:text-accent-hover",
  success:
    "border border-success/25 bg-success-soft text-success hover:border-success/40",
  danger: "border border-danger/25 bg-surface text-danger hover:bg-danger-soft",
};

const sizes: Record<Size, string> = {
  sm: "px-2.5 py-1.5 text-xs",
  md: "px-4 py-2 text-sm",
};

/**
 * Styled wrapper around a native <button> — forwards every standard
 * button prop (type, disabled, onClick, ...) unchanged, so every existing
 * call site's mutation-pending/disabled/text-swap logic keeps working
 * exactly as it did before; only the visual treatment changes here.
 */
export function Button({
  variant = "secondary",
  size = "md",
  className = "",
  ...props
}: ButtonProps) {
  return (
    <button
      className={`${base} ${variants[variant]} ${sizes[size]} ${className}`}
      {...props}
    />
  );
}
