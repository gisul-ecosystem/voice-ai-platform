import Link from "next/link";

import { LandingNav } from "@/components/interviewer/LandingNav";
import { SavedInterviewers } from "@/components/interviewer/SavedInterviewers";

export default function InterviewerPage() {
  return (
    <main className="interviewer-home">
      <LandingNav
        ariaLabel="AI Interviewer navigation"
        trailing={
          <>
            <Link href="/interviewer/results">Review a scorecard</Link>
            <span className="environment-badge">Reference environment</span>
          </>
        }
      />

      <section className="interviewer-hero">
        <div className="hero-copy">
          <p className="eyebrow">Structured voice interviews</p>
          <h1>Consistent interviews, with space for real conversation.</h1>
          <p className="hero-lead">
            Configure a job-related interview, invite a candidate, and run a
            focused AI-led conversation with consent and live transcription.
          </p>
          <div className="hero-actions">
            <Link className="button primary" href="/interviewer/admin/design">
              Create an interview
            </Link>
            <span>Or reuse a saved interview below to invite more candidates.</span>
          </div>
        </div>
        <aside className="journey-overview" aria-label="Interview journey">
          <p className="step-label">One clear workflow</p>
          <ol>
            <li>
              <span>01</span>
              <div>
                <strong>Design</strong>
                <p>Role, competencies and policy</p>
              </div>
            </li>
            <li>
              <span>02</span>
              <div>
                <strong>Align</strong>
                <p>Confirm topics and evidence, then publish</p>
              </div>
            </li>
            <li>
              <span>03</span>
              <div>
                <strong>Invite</strong>
                <p>Signed, time-bound candidate access</p>
              </div>
            </li>
            <li>
              <span>04</span>
              <div>
                <strong>Results</strong>
                <p>Scorecard, evidence, human override</p>
              </div>
            </li>
          </ol>
        </aside>
      </section>

      <section className="trust-strip" aria-label="Interview safeguards">
        <div>
          <strong>Job-related</strong>
          <span>Structured competency coverage</span>
        </div>
        <div>
          <strong>Consent first</strong>
          <span>Disclosures before device access</span>
        </div>
        <div>
          <strong>Private by design</strong>
          <span>Credentials stay server-side</span>
        </div>
      </section>

      <SavedInterviewers />
    </main>
  );
}
