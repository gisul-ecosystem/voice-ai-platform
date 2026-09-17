import Link from "next/link";

import { CandidateInterviewJourney } from "@/components/CandidateInterviewJourney";

export default async function AttendInterviewPage({
  searchParams,
}: {
  searchParams: Promise<{ invitation?: string }>;
}) {
  const { invitation } = await searchParams;
  return (
    <main className="demo-page demo-stage-candidate">
      <nav className="topbar" aria-label="Candidate interview navigation">
        <Link href="/interviewer" className="brand">AI Interviewer</Link>
        <span>Candidate reference flow</span>
      </nav>
      <section className="demo-intro">
        <p className="eyebrow">Secure interview</p>
        <h1>Candidate journey</h1>
        <p>Verify your invitation before granting device permissions.</p>
      </section>
      <section className="demo-card">
        {invitation ? (
          <CandidateInterviewJourney invitationToken={invitation} />
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
