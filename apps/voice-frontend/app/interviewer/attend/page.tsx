import Link from "next/link";

import { CandidateInterviewJourney } from "@/components/CandidateInterviewJourney";

export default async function AttendInterviewPage({
  searchParams,
}: {
  searchParams: Promise<{ invitation?: string | string[] }>;
}) {
  const params = await searchParams;
  const invitationRaw = params.invitation;
  const invitation = Array.isArray(invitationRaw)
    ? invitationRaw[0]
    : invitationRaw;
  const invitationToken =
    typeof invitation === "string" && invitation.trim()
      ? invitation.trim()
      : undefined;

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
