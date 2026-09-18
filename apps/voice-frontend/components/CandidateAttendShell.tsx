"use client";

import Link from "next/link";
import { useState } from "react";

import { CandidateInterviewJourney } from "@/components/CandidateInterviewJourney";

export function CandidateAttendShell({
  invitationToken,
}: {
  invitationToken?: string;
}) {
  const [stage, setStage] = useState("candidate");

  return (
    <main className={`demo-page demo-stage-${invitationToken ? stage : "candidate"}`}>
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
        {invitationToken ? (
          <CandidateInterviewJourney
            invitationToken={invitationToken}
            onStageChange={setStage}
          />
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
