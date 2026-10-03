"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { ApiError, login, register, setToken } from "../../lib/api";
import { SignupField } from "../../components/SignupField";
import { EMAIL_RE, FIELD_LABELS, LabeledInput, LabeledPasswordInput, type FocusTarget } from "../../components/AuthFieldKit";
import { BrandMark } from "../../components/ui/icons";

// "Entering the AgentOps AI control plane" — the shared Intelligence Field
// visual system (SignupField.tsx + globals.css's `.signup-canvas` block)
// used by both /register and /login, replacing the old AuthBranding
// panel on both screens.

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [passwordVisible, setPasswordVisible] = useState(false);
  const [focusField, setFocusField] = useState<FocusTarget>(null);
  const [ctaActive, setCtaActive] = useState(false);

  const nameValid = fullName.trim().length > 1;
  const emailValid = EMAIL_RE.test(email);
  const passwordValid = password.length >= 8;

  const mutation = useMutation({
    mutationFn: async () => {
      await register(email, password, fullName);
      // Registration doesn't return a token — log in immediately after so
      // a new user lands in the app in one step, not a second form.
      return login(email, password);
    },
    onSuccess: (token) => {
      setToken(token.access_token);
      router.push("/home");
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    mutation.mutate();
  }

  function clearFocus(field: FocusTarget) {
    setFocusField((current) => (current === field ? null : current));
  }

  return (
    <main className="signup-canvas relative min-h-screen w-full overflow-hidden">
      <div aria-hidden className="pointer-events-none absolute inset-0 z-0">
        <div className="bg-technical-grid-dark absolute inset-0 opacity-70" />
        <div className="signup-vignette absolute inset-0" />
      </div>

      {/* The Intelligence Field — compact block above the form on mobile,
          a full-bleed background behind an asymmetric form module from
          lg up. Mobile drops a few of the farther/smaller nodes and
          particles via the `hidden lg:block` tags inside SignupField. */}
      <div aria-hidden className="relative z-[1] h-56 w-full sm:h-72 lg:absolute lg:inset-0 lg:h-full lg:w-full">
        <SignupField focusField={focusField} passwordValid={passwordValid} ctaActive={ctaActive} className="h-full w-full" />

        <div className="pointer-events-none absolute inset-0 hidden lg:block">
          {FIELD_LABELS.map((label) => (
            <span
              key={label.text}
              className="signup-label absolute font-mono text-[10px] uppercase tracking-[0.25em] text-ink-3"
              style={{ top: label.top, left: label.left, animationDelay: label.delay }}
            >
              {label.text}
            </span>
          ))}
        </div>
      </div>

      <div className="relative z-10 flex min-h-screen w-full flex-col">
        <Link
          href="/"
          className="flex items-center gap-2 px-6 py-6 text-sm font-medium tracking-tight text-ink-2 no-underline lg:px-12 lg:py-8"
        >
          <BrandMark className="text-ink-3" />
          AgentOps AI
        </Link>

        <div className="flex flex-1 flex-col items-center justify-center px-6 pb-14 lg:items-end lg:justify-center lg:pr-[9%]">
          <div className="signup-form-panel w-full max-w-sm rounded-[14px] p-7 lg:p-8">
            <p className="text-eyebrow font-mono" style={{ color: "var(--signup-violet)" }}>
              Join the control plane
            </p>

            <h1 className="mt-3 text-[1.8rem] leading-[1.2] text-ink">
              Build with{" "}
              <span className="font-instrument italic" style={{ fontSize: "1.2em" }}>
                confidence.
              </span>
            </h1>

            <p className="mt-3 text-sm leading-relaxed text-ink-2">
              Run, evaluate, and safeguard AI agents from experiment to production.
            </p>

            <form onSubmit={handleSubmit} className="mt-7 flex flex-col gap-4">
              <LabeledInput
                label="Full name"
                id="fullName"
                type="text"
                placeholder="Your name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                onFocus={() => setFocusField("name")}
                onBlur={() => clearFocus("name")}
                autoComplete="name"
                valid={nameValid}
              />

              <LabeledInput
                label="Email address"
                id="email"
                type="email"
                placeholder="you@company.com"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onFocus={() => setFocusField("email")}
                onBlur={() => clearFocus("email")}
                autoComplete="email"
                valid={emailValid}
              />

              <LabeledPasswordInput
                label="Password"
                id="password"
                placeholder="Create a password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onFocus={() => setFocusField("password")}
                onBlur={() => clearFocus("password")}
                autoComplete="new-password"
                visible={passwordVisible}
                onToggleVisible={() => setPasswordVisible((v) => !v)}
                valid={passwordValid}
              />

              {mutation.isError && (
                <p className="rounded-[8px] border border-danger/25 bg-danger-soft px-3 py-2 text-sm text-danger">
                  {mutation.error instanceof ApiError
                    ? mutation.error.message
                    : "Something went wrong. Please try again."}
                </p>
              )}

              <button
                type="submit"
                disabled={mutation.isPending}
                onMouseEnter={() => setCtaActive(true)}
                onMouseLeave={() => setCtaActive(false)}
                className="signup-cta mt-1.5 inline-flex items-center justify-center gap-1.5 rounded-[8px] px-4 py-2.5 text-sm font-medium tracking-[0.04em]"
              >
                {mutation.isPending ? "CREATING ACCOUNT…" : "CREATE ACCOUNT"}
              </button>
            </form>

            <p className="mt-6 text-center text-xs text-ink-3">
              Already have an account?{" "}
              <Link href="/login" className="font-medium text-ink-2 no-underline hover:text-ink">
                Sign in →
              </Link>
            </p>
          </div>
        </div>
      </div>
    </main>
  );
}
