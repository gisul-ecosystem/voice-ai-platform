"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function TemplateResultsLookup() {
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
    <section className="template-hub-section" aria-label="Results">
      <div className="template-hub-panel-intro">
        <div>
          <h2>Results</h2>
          <p>Paste a session id from a completed interview for this template.</p>
        </div>
      </div>
      {error ? (
        <div className="alert" role="alert">
          {error}
        </div>
      ) : null}
      <div className="template-results-form">
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
          <span>
            Do not use scores for hiring until a reviewer has recorded a
            decision.
          </span>
          <button
            className="button primary"
            type="button"
            onClick={openScorecard}
          >
            Open scorecard
          </button>
        </div>
      </div>
    </section>
  );
}
