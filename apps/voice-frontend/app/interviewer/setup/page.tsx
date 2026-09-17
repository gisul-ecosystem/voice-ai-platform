import Link from "next/link";

import { RecruiterInterviewSetup } from "@/components/RecruiterInterviewSetup";

export default function InterviewSetupPage() {
  return (
    <main className="demo-page recruiter-page">
      <nav className="topbar" aria-label="Interview setup navigation">
        <Link href="/interviewer" className="brand">AI Interviewer</Link>
        <span>Interview workspace</span>
      </nav>
      <section className="demo-intro">
        <p className="eyebrow">Create and schedule</p>
        <h1>Create a structured interview</h1>
        <p>
          Define the role, interview depth, candidate experience and consent
          policy before scheduling.
        </p>
      </section>
      <section className="demo-card">
        <RecruiterInterviewSetup />
      </section>
    </main>
  );
}
