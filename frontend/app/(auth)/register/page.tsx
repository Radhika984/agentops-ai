"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { ApiError, login, register, setToken } from "../../lib/api";
import { AuthBranding } from "../../components/AuthBranding";
import { Button } from "../../components/ui/Button";
import { Field, PasswordField } from "../../components/ui/Input";
import { ArrowRightIcon, BrandMark, CostIcon, GoalIcon, ProjectsIcon } from "../../components/ui/icons";

const BULLETS = [
  { icon: ProjectsIcon, title: "Create projects", detail: "Organize your agent workflows" },
  { icon: GoalIcon, title: "Run evaluations", detail: "Test, verify and improve each run" },
  { icon: CostIcon, title: "Track cost & performance", detail: "Stay efficient and informed" },
];

export default function RegisterPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");

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

  return (
    <main className="grid min-h-screen md:grid-cols-2">
      <AuthBranding
        headline="Build your AgentOps workspace."
        description="Start running, evaluating and releasing AI agents with confidence."
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

          <h1 className="font-serif text-3xl text-ink">Create your workspace</h1>
          <p className="mt-1.5 text-sm text-ink-2">
            A workspace is where your projects, agent runs and evaluations live.
          </p>

          <form onSubmit={handleSubmit} className="mt-7 flex flex-col gap-4">
            <Field
              label="Full name"
              type="text"
              placeholder="Your name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
              autoComplete="name"
            />

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
              placeholder="Create a password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />

            {mutation.isError && (
              <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">
                {mutation.error instanceof ApiError
                  ? mutation.error.message
                  : "Something went wrong. Please try again."}
              </p>
            )}

            <Button type="submit" variant="primary" disabled={mutation.isPending} className="mt-1.5">
              {mutation.isPending ? "Creating account…" : "Create account"}
              {!mutation.isPending && <ArrowRightIcon />}
            </Button>
          </form>

          <p className="mt-6 text-center text-sm text-ink-3">
            Already have an account?{" "}
            <Link href="/login" className="font-medium text-accent no-underline hover:underline">
              Sign in
            </Link>
          </p>
        </div>
      </div>
    </main>
  );
}
