"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { LandingNav, AdminProgress } from "@/components/interviewer/LandingNav";

export default function ScorecardLookupPage() {
  const router = useRouter();
  const [sessionId, setSessionId] = useState("");
  const [error, setError] = useState("");

  function openScorecard() {
    const value = sessionId.trim();
    if (value.length < 8) {
      setError("Enter a valid session id.");
      return;
    }
    setError("");
    router.push(`/interviewer/sessions/${encodeURIComponent(value)}/scorecard`);
  }

  return (
    <main className="interviewer-home admin-builder-page">
      <LandingNav ariaLabel="Reviewer navigation" badge="04 Results" />
      <AdminProgress current="results" />
      <section className="demo-intro">
        <p className="eyebrow">Human review</p>
        <h1>Open a completed scorecard</h1>
        <p>
          Coverage, excerpts, and missing intents stay advisory until a person
          accepts or overrides the result.
        </p>
      </section>
      <section className="demo-card admin-section">
        {error ? <div className="alert" role="alert">{error}</div> : null}
        <label>
          Session id
          <input
            value={sessionId}
            onChange={(event) => setSessionId(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                openScorecard();
              }
            }}
            placeholder="ses_..."
            autoComplete="off"
          />
        </label>
        <div className="admin-page-actions">
          <span>Do not use scores for hiring until a reviewer has recorded a decision.</span>
          <button className="button primary" type="button" onClick={openScorecard}>
            Open scorecard
          </button>
        </div>
      </section>
    </main>
  );
}
