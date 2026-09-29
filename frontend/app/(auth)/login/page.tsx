"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { ApiError, login, setToken } from "../../lib/api";
import { AuthBranding } from "../../components/AuthBranding";
import { Button } from "../../components/ui/Button";
import { Field, PasswordField } from "../../components/ui/Input";
import { ArrowRightIcon, BrandMark, ReleaseIcon, SafetyIcon, ToolsIcon } from "../../components/ui/icons";

const BULLETS = [
  { icon: ToolsIcon, title: "Run & evaluate agents", detail: "Across the full lifecycle" },
  { icon: SafetyIcon, title: "Ensure safety & reliability", detail: "With multi-layer checks" },
  { icon: ReleaseIcon, title: "Release with confidence", detail: "Based on real data, not guesswork" },
];

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const mutation = useMutation({
    mutationFn: () => login(email, password),
    onSuccess: (token) => {
      setToken(token.access_token);
      router.push("/home");
    },
  });

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    mutation.mutate();
  }

  return (
    <main className="grid min-h-screen md:grid-cols-2">
      <AuthBranding
        headline="Welcome back to your evaluation workspace."
        description="Sign in to pick up where you left off — projects, agent runs and release reviews."
        bullets={BULLETS}
      />

      <div className="animate-fade-in flex flex-col justify-center px-6 py-12 md:px-12 lg:px-16">
        <div className="mx-auto w-full max-w-sm">
          <Link
            href="/"
            className="mb-8 flex items-center gap-2 text-sm font-semibold tracking-tight text-ink no-underline md:hidden"
          >
            <BrandMark className="text-accent" />
            AgentOps AI
          </Link>

          <h1 className="font-serif text-3xl text-ink">Sign in</h1>
          <p className="mt-1.5 text-sm text-ink-2">Enter your email and password to continue.</p>

          <form onSubmit={handleSubmit} className="mt-7 flex flex-col gap-4">
            <Field
              label="Email address"
              type="email"
              placeholder="you@example.com"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />

            <PasswordField
              label="Password"
              placeholder="Enter your password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />

            {mutation.isError && (
              <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                {mutation.error instanceof ApiError
                  ? mutation.error.message
                  : "Something went wrong. Please try again."}
              </p>
            )}

            <Button type="submit" variant="primary" disabled={mutation.isPending} className="mt-1.5">
              {mutation.isPending ? "Signing in…" : "Sign in"}
              {!mutation.isPending && <ArrowRightIcon />}
            </Button>
          </form>

          <p className="mt-6 text-center text-sm text-ink-3">
            Don&apos;t have an account?{" "}
            <Link href="/register" className="font-medium text-accent no-underline hover:underline">
              Create one
            </Link>
          </p>
        </div>
      </div>
    </main>
  );
}
