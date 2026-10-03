"use client";

import type { InputHTMLAttributes } from "react";
import { EyeIcon, EyeOffIcon } from "./ui/icons";

/**
 * Shared building blocks for the two "Intelligence Field" auth screens
 * (/register and /login) — kept separate from the generic Field/
 * PasswordField in ui/Input.tsx because these carry the signup-canvas-
 * specific cyan validity dot and violet→blue focus-sweep, and must not
 * change how every other screen's inputs look or behave.
 */

export type FocusTarget = "name" | "email" | "password" | null;

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// Low-opacity Geist Mono annotations around the Intelligence Field —
// decorative system vocabulary, never real metrics. Positioned by hand to
// sit in the field's open space, clear of where the form panel lands on
// the right on both auth screens.
export const FIELD_LABELS = [
  { text: "AGENT GRAPH", top: "12%", left: "7%", delay: "0s" },
  { text: "RUNTIME", top: "38%", left: "3%", delay: "1.3s" },
  { text: "EVALUATION", top: "66%", left: "12%", delay: "2.6s" },
  { text: "POLICY", top: "8%", left: "58%", delay: "0.9s" },
  { text: "SAFETY", top: "80%", left: "44%", delay: "3.2s" },
  { text: "TRACE", top: "46%", left: "53%", delay: "1.9s" },
  { text: "CONTROL PLANE", top: "6%", left: "81%", delay: "2.3s" },
];

const inputClass =
  "signup-input w-full rounded-[8px] border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3 transition-colors duration-150 focus-visible:outline-none";

function ValidityDot({ offset = "right-3" }: { offset?: string }) {
  return (
    <span
      className={`absolute ${offset} h-1.5 w-1.5 rounded-full`}
      style={{ background: "var(--signup-cyan)", boxShadow: "0 0 6px rgba(6,182,212,0.85)" }}
    />
  );
}

interface LabeledInputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  valid?: boolean;
}

export function LabeledInput({ label, id, valid, className = "", ...props }: LabeledInputProps) {
  return (
    <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2" htmlFor={id}>
      {label}
      <span className="relative flex items-center">
        <input id={id} className={`${inputClass} ${className}`} {...props} />
        {valid && <ValidityDot />}
      </span>
    </label>
  );
}

interface LabeledPasswordInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label: string;
  valid?: boolean;
  visible: boolean;
  onToggleVisible: () => void;
}

export function LabeledPasswordInput({
  label,
  id,
  valid,
  visible,
  onToggleVisible,
  className = "",
  ...props
}: LabeledPasswordInputProps) {
  return (
    <label className="flex flex-col gap-1.5 text-sm font-medium text-ink-2" htmlFor={id}>
      {label}
      <span className="relative flex items-center">
        <input id={id} type={visible ? "text" : "password"} className={`${inputClass} pr-10 ${className}`} {...props} />
        {valid && <ValidityDot offset="right-9" />}
        <button
          type="button"
          onClick={onToggleVisible}
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
