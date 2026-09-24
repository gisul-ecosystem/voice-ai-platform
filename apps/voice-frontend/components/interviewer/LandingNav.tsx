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

/** Create-template flow only: Design → Align. */
const CREATE_STEPS = [
  { href: "/interviewer/admin/design", label: "Design", step: "01", id: "design" },
  { href: "/interviewer/admin/review", label: "Align", step: "02", id: "review" },
] as const;

type CreateProgressProps = {
  current: "design" | "review";
};

export function CreateProgress({ current }: CreateProgressProps) {
  const currentIndex = CREATE_STEPS.findIndex((item) => item.id === current);
  return (
    <div className="admin-progress" aria-label="New template steps">
      {CREATE_STEPS.map((item, index) => {
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

/** @deprecated Use CreateProgress for new-template flow. */
export function AdminProgress({
  current,
}: {
  current: "design" | "review" | "invite" | "results";
}) {
  if (current === "design" || current === "review") {
    return <CreateProgress current={current} />;
  }
  return null;
}

const HUB_TABS = [
  { id: "invite", label: "Invite" },
  { id: "invites", label: "Invites" },
  { id: "results", label: "Results" },
] as const;

type HubTabId = (typeof HUB_TABS)[number]["id"];

type TemplateHubNavProps = {
  definitionId: string;
  current: HubTabId;
  onNavigate?: (tab: HubTabId) => void;
};

export function TemplateHubNav({
  definitionId,
  current,
  onNavigate,
}: TemplateHubNavProps) {
  return (
    <nav className="template-hub-tabs" aria-label="Template actions">
      {HUB_TABS.map((item) => {
        const active = item.id === current;
        const href =
          item.id === "invite"
            ? `/interviewer/templates/${encodeURIComponent(definitionId)}`
            : `/interviewer/templates/${encodeURIComponent(definitionId)}?tab=${item.id}`;
        return (
          <Link
            key={item.id}
            href={href}
            className={["template-hub-tab", active ? "is-active" : ""]
              .filter(Boolean)
              .join(" ")}
            aria-current={active ? "page" : undefined}
            onClick={(event) => {
              if (!onNavigate) return;
              event.preventDefault();
              onNavigate(item.id);
            }}
          >
            {item.label}
          </Link>
        );
      })}
    </nav>
  );
}
