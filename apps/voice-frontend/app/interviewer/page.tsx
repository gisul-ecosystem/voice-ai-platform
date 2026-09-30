import Link from "next/link";

import { LandingNav } from "@/components/interviewer/LandingNav";
import { SavedInterviewers } from "@/components/interviewer/SavedInterviewers";

export default function InterviewerPage() {
  return (
    <main className="interviewer-home template-library-page">
      <LandingNav
        ariaLabel="AI Interviewer navigation"
        trailing={
          <>
            <Link href="/interviewer/results">Scorecards</Link>
            <Link className="button primary" href="/interviewer/admin/design">
              New template
            </Link>
          </>
        }
      />

      <header className="template-library-header">
        <div>
          <p className="eyebrow">AI Interviewer</p>
          <h1>Templates</h1>
          <p>
            Each template is a reusable interview. Open one to invite
            candidates, manage links, or review results.
          </p>
        </div>
      </header>

      <SavedInterviewers />
    </main>
  );
}
