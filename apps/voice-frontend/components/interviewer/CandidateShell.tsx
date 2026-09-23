import Link from "next/link";
import type { ReactNode } from "react";

type CandidateShellProps = {
  children: ReactNode;
  title?: string;
  lead?: string;
};

/** Shared candidate invite / join chrome (canonical join surface). */
export function CandidateShell({
  children,
  title = "Your AI interview",
  lead = "Review the details and consent before granting microphone access.",
}: CandidateShellProps) {
  return (
    <main className="demo-page demo-stage-candidate">
      <nav className="landing-nav" aria-label="Candidate interview navigation">
        <Link href="/interviewer" className="brand">
          <span className="brand-mark" aria-hidden="true">
            AI
          </span>
          AI Interviewer
        </Link>
        <span className="environment-badge">Candidate interview</span>
      </nav>
      <section className="demo-intro">
        <p className="eyebrow">Secure interview</p>
        <h1>{title}</h1>
        <p>{lead}</p>
      </section>
      <section className="demo-card">{children}</section>
    </main>
  );
}
