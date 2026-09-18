"use client";

import Link from "next/link";
import { useState } from "react";

import { SetupForm } from "@/components/SetupForm";
import { getProduct } from "@/lib/products";
import type { PublicSessionRequest } from "@/lib/session-contract";

type CreatedInterview = {
  interviewId: string;
  candidatePath: string;
  startsAt: string;
};

export function RecruiterInterviewSetup() {
  const [draft, setDraft] = useState<PublicSessionRequest>();
  const [created, setCreated] = useState<CreatedInterview>();
  const [error, setError] = useState<string>();
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);

  async function schedule(value: PublicSessionRequest) {
    setDraft(value);
    setSaving(true);
    setError(undefined);
    try {
      const response = await fetch("/api/interviews", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          candidateName: value.participantName,
          candidateEmail: value.candidateEmail,
          startsAt: value.startsAt,
          timezone: value.timezone,
          jobDescription: value.jobDescription,
          resumeText: value.resumeText,
          interviewSetup: value.interviewSetup,
        }),
      });
      const data = (await response.json().catch(() => ({}))) as {
        error?: string;
      } & Partial<CreatedInterview>;
      if (!response.ok || !data.interviewId || !data.candidatePath) {
        throw new Error(data.error || "The interview could not be scheduled.");
      }
      setCreated(data as CreatedInterview);
      sessionStorage.removeItem("ai-interviewer:setup-draft");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The interview could not be scheduled.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (created) {
    const candidateUrl =
      typeof window === "undefined"
        ? created.candidatePath
        : `${window.location.origin}${created.candidatePath}`;
    return (
      <div className="scheduled-confirmation">
        <span className="completion-mark" aria-hidden="true">✓</span>
        <p className="step-label">Interview scheduled</p>
        <h2>Candidate invitation is ready</h2>
        <p>
          The production product sends this link through its branded email
          workflow. The reference application exposes it for end-to-end testing.
        </p>
        {error ? <div className="alert" role="alert">{error}</div> : null}
        <div className="invitation-link">
          <label htmlFor="candidate-link">Candidate URL</label>
          <div className="copy-field">
            <input id="candidate-link" readOnly value={candidateUrl} />
            <button
              className="button secondary compact-button"
              type="button"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(candidateUrl);
                  setCopied(true);
                } catch {
                  setError("Copy was blocked. Select and copy the URL manually.");
                }
              }}
            >
              {copied ? "Copied" : "Copy link"}
            </button>
          </div>
          <p className="form-note" role="status">
            {copied
              ? "Invitation link copied."
              : "Share this complete signed link with the candidate."}
          </p>
        </div>
        <div className="button-row">
          <Link className="button primary" href={created.candidatePath}>
            Open candidate journey
          </Link>
          <button className="button secondary" type="button"
            onClick={() => {
              setCreated(undefined);
              setCopied(false);
              setError(undefined);
            }}>
            Create another
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      className="recruiter-setup-shell"
      onClick={() => {
        if (error) setError(undefined);
      }}
    >
      {error ? <div className="alert" role="alert">{error}</div> : null}
      {saving ? (
        <div className="center-state" role="status">
          <span className="spinner" aria-hidden="true" />
          <h2>Scheduling interview</h2>
        </div>
      ) : (
        <SetupForm
          product={getProduct("interviewer")}
          initialValue={draft}
          onContinue={schedule}
        />
      )}
    </div>
  );
}
