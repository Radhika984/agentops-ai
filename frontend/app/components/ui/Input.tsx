"use client";

import { useId, useState, type InputHTMLAttributes, type ReactNode } from "react";
import { EyeIcon, EyeOffIcon } from "./icons";

// backdrop-blur-md pairs with the same translucent-surface recipe Card.tsx
// uses (bg-surface is opaque on the light theme, genuinely translucent on
// the dark .app-canvas theme — see globals.css) so the search field and
// every form input read as frosted glass on the dashboard, not a flat box.
const inputClasses =
  "w-full rounded-control border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3 backdrop-blur-md transition-all duration-150 focus-visible:border-accent focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-accent/15 disabled:opacity-50";

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode;
}

/** Label + input pair with consistent styling — forwards every native
 * input prop unchanged (value, onChange, type, required, minLength, ...)
 * so existing form state/validation logic keeps working untouched. */
export function Field({ label, id, className = "", ...props }: FieldProps) {
  return (
    <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2" htmlFor={id}>
      {label}
      <input id={id} className={`${inputClasses} ${className}`} {...props} />
    </label>
  );
}

/** A bare input with the same visual treatment, for places that don't
 * want the wrapping <label> (e.g. an inline composer next to a button). */
export function TextInput({ className = "", ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={`${inputClasses} ${className}`} {...props} />;
}

/** Password field with a show/hide toggle — purely a frontend affordance
 * (a local `visible` useState controlling the input's `type`), no change
 * to how the password value itself is captured, validated or submitted.
 * Forwards every native input prop the same way Field does. */
export function PasswordField({
  label,
  id,
  className = "",
  ...props
}: Omit<FieldProps, "type">) {
  const [visible, setVisible] = useState(false);
  const generatedId = useId();
  const inputId = id ?? generatedId;

  return (
    <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2" htmlFor={inputId}>
      {label}
      <span className="relative flex items-center">
        <input
          id={inputId}
          type={visible ? "text" : "password"}
          className={`${inputClasses} pr-10 ${className}`}
          {...props}
        />
        <button
          type="button"
          onClick={() => setVisible((v) => !v)}
          className="absolute right-2.5 text-ink-3 transition-colors duration-150 hover:text-ink"
          aria-label={visible ? "Hide password" : "Show password"}
          tabIndex={-1}
        >
          {visible ? <EyeOffIcon /> : <EyeIcon />}
        </button>
      </span>
    </label>
  );
}
