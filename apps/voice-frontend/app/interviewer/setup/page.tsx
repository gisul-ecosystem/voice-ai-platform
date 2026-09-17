import Link from "next/link";

import { RecruiterInterviewSetup } from "@/components/RecruiterInterviewSetup";

export default function InterviewSetupPage() {
  return (
    <main className="demo-page">
      <nav className="topbar" aria-label="Interview setup navigation">
        <Link href="/interviewer" className="brand">AI Interviewer</Link>
        <span>Recruiter reference flow</span>
      </nav>
      <section className="demo-intro">
        <p className="eyebrow">Create and schedule</p>
        <h1>Interview setup</h1>
        <p>Build a structured, job-related interview and candidate invitation.</p>
      </section>
      <section className="demo-card">
        <RecruiterInterviewSetup />
      </section>
    </main>
  );
}
