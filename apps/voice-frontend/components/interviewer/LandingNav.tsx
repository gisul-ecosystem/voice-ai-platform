import Link from "next/link";
import type { ReactNode } from "react";

type LandingNavProps = {
  badge?: string;
  ariaLabel?: string;
  homeHref?: string;
  trailing?: ReactNode;
};

export function LandingNav({
  badge,
  ariaLabel = "AI Interviewer navigation",
  homeHref = "/interviewer",
  trailing,
}: LandingNavProps) {
  return (
    <nav className="landing-nav" aria-label={ariaLabel}>
      <Link href={homeHref} className="brand">
        <span className="brand-mark" aria-hidden="true">
          AI
        </span>
        AI Interviewer
      </Link>
      {trailing ? (
        <div className="landing-nav-actions">{trailing}</div>
      ) : badge ? (
        <span className="environment-badge">{badge}</span>
      ) : null}
    </nav>
  );
}

const ADMIN_STEPS = [
  { href: "/interviewer/admin/design", label: "Design", step: "01", id: "design" },
  { href: "/interviewer/admin/review", label: "Align", step: "02", id: "review" },
  { href: "/interviewer/admin/invite", label: "Invite", step: "03", id: "invite" },
] as const;

type AdminProgressProps = {
  current: "design" | "review" | "invite";
};

export function AdminProgress({ current }: AdminProgressProps) {
  const currentIndex = ADMIN_STEPS.findIndex((item) => item.id === current);
  return (
    <div className="admin-progress" aria-label="Interview setup steps">
      {ADMIN_STEPS.map((item, index) => {
        const active = index === currentIndex;
        const done = index < currentIndex;
        return (
          <Link
            key={item.href}
            href={item.href}
            className={[
              "admin-progress-step",
              active ? "is-active" : "",
              done ? "is-done" : "",
            ]
              .filter(Boolean)
              .join(" ")}
            aria-current={active ? "step" : undefined}
          >
            <span>{item.step}</span>
            {item.label}
          </Link>
        );
      })}
    </div>
  );
}
