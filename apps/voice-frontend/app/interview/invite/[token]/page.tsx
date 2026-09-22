import Link from "next/link";

import { CandidateInterviewJourney } from "@/components/CandidateInterviewJourney";

export default async function CandidateInvitePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const invitationToken = decodeURIComponent(token || "").trim();

  return (
    <main className="demo-page demo-stage-candidate">
      <nav className="topbar" aria-label="Candidate interview navigation">
        <Link href="/interviewer" className="brand">
          AI Interviewer
        </Link>
        <span>Candidate interview</span>
      </nav>
      <section className="demo-intro">
        <p className="eyebrow">Secure interview</p>
        <h1>Your AI interview</h1>
        <p>Review the details and consent before granting microphone access.</p>
      </section>
      <section className="demo-card">
        {invitationToken ? (
          <CandidateInterviewJourney invitationToken={invitationToken} />
        ) : (
          <div className="center-state">
            <h2>Invitation required</h2>
            <p>Open the complete link provided by the inviting organization.</p>
          </div>
        )}
      </section>
    </main>
  );
}
