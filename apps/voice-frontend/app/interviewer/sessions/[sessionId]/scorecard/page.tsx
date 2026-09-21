"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

type CompetencyScore = {
  competency_id?: string;
  rating?: number | null;
  outcome?: string;
  anchor?: string | null;
  excerpts?: string[];
  missing_intents?: string[];
  missing_evidence?: string[];
};

type Scorecard = {
  session_id?: string;
  definition_id?: string;
  overall_recommendation?: string;
  human_review_status?: string;
  override_reason?: string | null;
  reviewer_id?: string | null;
  next_human_questions?: string[];
  competencies?: CompetencyScore[];
  quality_metrics?: {
    mandatory_coverage_pct?: number;
    not_assessed_rate?: number;
    insufficient_evidence_rate?: number;
    question_count?: number;
    answer_count?: number;
  };
};

function label(value: string | null | undefined) {
  return (value || "pending").replaceAll("_", " ");
}

function sessionIdFromParams(raw: unknown) {
  const value = String(raw || "").trim();
  try {
    return decodeURIComponent(value).trim();
  } catch {
    return value;
  }
}

export default function ScorecardReviewPage() {
  const params = useParams<{ sessionId: string }>();
  const sessionId = sessionIdFromParams(params.sessionId);
  const [scorecard, setScorecard] = useState<Scorecard | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reviewerId, setReviewerId] = useState("");
  const [overrideReason, setOverrideReason] = useState("");

  const load = useCallback(async () => {
    if (sessionId.length < 8) {
      setError("Invalid session.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/scorecard`, {
        cache: "no-store",
      });
      const data = (await response.json().catch(() => ({}))) as Scorecard & { error?: string };
      if (!response.ok) {
        throw new Error(data.error || "Scorecard could not be loaded.");
      }
      setScorecard(data);
    } catch (reason) {
      setScorecard(null);
      setError(reason instanceof Error ? reason.message : "Scorecard could not be loaded.");
    } finally {
      setBusy(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function submit(status: "approved" | "overridden") {
    if (!reviewerId.trim()) {
      setError("Enter who is reviewing this scorecard.");
      return;
    }
    if (status === "overridden" && overrideReason.trim().length < 2) {
      setError("A reason is required to override this scorecard.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/scorecard`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          status,
          reviewer_id: reviewerId.trim(),
          override_reason: status === "overridden" ? overrideReason.trim() : undefined,
        }),
      });
      const data = (await response.json().catch(() => ({}))) as Scorecard & { error?: string };
      if (!response.ok) {
        throw new Error(data.error || "The review could not be saved.");
      }
      setScorecard(data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The review could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  const metrics = scorecard?.quality_metrics;
  const pending = (scorecard?.human_review_status || "pending") === "pending";

  return (
    <main className="interviewer-home admin-builder-page">
      <nav className="landing-nav" aria-label="Reviewer navigation">
        <Link href="/interviewer" className="brand">
          <span className="brand-mark" aria-hidden="true">AI</span>
          AI Interviewer
        </Link>
        <Link className="environment-badge" href="/interviewer/results">Find another session</Link>
      </nav>
      <section className="demo-intro">
        <p className="eyebrow">Human review</p>
        <h1>Scorecard for this interview</h1>
        <p>
          Ratings are advisory. Compare excerpts against the published 1 / 3 / 5
          anchors, then accept or override with a reason before any hiring use.
        </p>
      </section>

      {error ? <div className="alert" role="alert">{error}</div> : null}

      {!scorecard && !error ? (
        <section className="demo-card"><p>{busy ? "Loading scorecard..." : "Scorecard is not available yet."}</p></section>
      ) : null}

      {scorecard ? (
        <>
          <section className="scorecard-summary" aria-label="Scorecard summary">
            <article>
              <p className="step-label">Recommendation</p>
              <strong>{label(scorecard.overall_recommendation)}</strong>
            </article>
            <article>
              <p className="step-label">Human review</p>
              <strong>{label(scorecard.human_review_status)}</strong>
            </article>
            <article>
              <p className="step-label">Coverage</p>
              <strong>{Math.round(metrics?.mandatory_coverage_pct || 0)}%</strong>
            </article>
            <article>
              <p className="step-label">Not assessed</p>
              <strong>{Math.round((metrics?.not_assessed_rate || 0) * 100)}%</strong>
            </article>
          </section>

          <section className="demo-card scorecard-list" aria-label="Competency evidence">
            {(scorecard.competencies || []).map((item) => (
              <article className="scorecard-competency" key={item.competency_id || item.anchor || "row"}>
                <header>
                  <h2>{label(item.competency_id)}</h2>
                  <span>{item.rating == null ? label(item.outcome) : `Rating ${item.rating}`}</span>
                </header>
                {item.anchor ? <p className="scorecard-anchor">{item.anchor}</p> : null}
                {(item.excerpts || []).length ? (
                  <ul className="scorecard-excerpts">
                    {(item.excerpts || []).map((excerpt, index) => (
                      <li key={`${item.competency_id || "c"}-excerpt-${index}`}>{excerpt}</li>
                    ))}
                  </ul>
                ) : (
                  <p className="section-help">No excerpt was recorded. This competency was not scored from candidate speech.</p>
                )}
                {(item.missing_intents || []).length ? (
                  <p className="scorecard-missing">Missing intents: {(item.missing_intents || []).join(", ")}</p>
                ) : null}
                {(item.missing_evidence || []).length ? (
                  <p className="scorecard-missing">Missing evidence: {(item.missing_evidence || []).join(", ")}</p>
                ) : null}
              </article>
            ))}
          </section>

          {(scorecard.next_human_questions || []).length ? (
            <section className="demo-card">
              <p className="step-label">Follow-up for a human interviewer</p>
              <ul className="scorecard-excerpts">
                {(scorecard.next_human_questions || []).map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="demo-card scorecard-review-form">
            <p className="step-label">Record a human decision</p>
            <label>
              Reviewer
              <input
                value={reviewerId}
                onChange={(event) => setReviewerId(event.target.value)}
                placeholder="you@company.com"
                disabled={!pending || busy}
              />
            </label>
            <label>
              Override reason
              <textarea
                rows={4}
                value={overrideReason}
                onChange={(event) => setOverrideReason(event.target.value)}
                placeholder="Required if you override the advisory score."
                disabled={!pending || busy}
              />
            </label>
            {scorecard.override_reason ? (
              <p className="section-help">Previous override: {scorecard.override_reason}</p>
            ) : null}
            <div className="admin-page-actions">
              <span>Hiring use requires an accept or an override with a reason.</span>
              <div className="scorecard-actions">
                <button
                  className="button secondary"
                  type="button"
                  disabled={!pending || busy}
                  onClick={() => void submit("overridden")}
                >
                  Override with reason
                </button>
                <button
                  className="button primary"
                  type="button"
                  disabled={!pending || busy}
                  onClick={() => void submit("approved")}
                >
                  Accept scorecard
                </button>
              </div>
            </div>
          </section>
        </>
      ) : null}
    </main>
  );
}
