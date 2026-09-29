import type { ReactNode } from "react";
import Link from "next/link";
import { BrandMark } from "./ui/icons";

interface Bullet {
  icon: (props: { className?: string }) => ReactNode;
  title: string;
  detail: string;
}

/**
 * The dark left-hand branding panel shared by /login and /register — a
 * headline plus a short, real feature summary (not marketing filler: each
 * line names a thing this app actually does). Reuses the --shell-*
 * surface family from AppShell's sidebar so the authenticated app and the
 * pre-auth screens read as the same product.
 */
export function AuthBranding({
  headline,
  description,
  bullets,
}: {
  headline: string;
  description: string;
  bullets: Bullet[];
}) {
  return (
    <div className="bg-technical-grid-dark relative hidden flex-col justify-between overflow-hidden bg-shell-bg px-10 py-10 md:flex lg:px-14 lg:py-14">
      <Link
        href="/"
        className="flex items-center gap-2 text-sm font-semibold tracking-tight text-shell-ink no-underline"
      >
        <BrandMark className="text-shell-accent" />
        AgentOps AI
      </Link>

      <div className="max-w-sm">
        <h2 className="font-serif text-3xl leading-tight text-shell-ink lg:text-4xl">{headline}</h2>
        <p className="mt-3 text-sm leading-relaxed text-shell-ink-3">{description}</p>

        <ul className="mt-9 flex flex-col gap-5">
          {bullets.map((bullet) => {
            const Icon = bullet.icon;
            return (
              <li key={bullet.title} className="flex items-start gap-3.5">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-shell-accent-soft text-shell-accent">
                  <Icon />
                </span>
                <div>
                  <p className="text-sm font-medium text-shell-ink">{bullet.title}</p>
                  <p className="text-xs text-shell-ink-3">{bullet.detail}</p>
                </div>
              </li>
            );
          })}
        </ul>
      </div>

      <p className="text-xs text-shell-ink-3">© {new Date().getFullYear()} AgentOps AI</p>
    </div>
  );
}
