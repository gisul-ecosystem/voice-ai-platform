"use client";

import { useState, type FormEvent } from "react";

import type { ProductConfig } from "@/lib/products";
import type { PublicSessionRequest } from "@/lib/session-contract";

type SetupFormProps = {
  product: ProductConfig;
  initialValue?: PublicSessionRequest;
  onContinue: (value: PublicSessionRequest) => void;
};

export function SetupForm({
  product,
  initialValue,
  onContinue,
}: SetupFormProps) {
  const [participantName, setParticipantName] = useState(
    initialValue?.participantName ?? "",
  );
  const [jobDescription, setJobDescription] = useState(
    initialValue?.jobDescription ?? "",
  );
  const [resumeText, setResumeText] = useState(
    initialValue?.resumeText ?? "",
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onContinue({
      productId: product.id,
      participantName: participantName.trim(),
      jobDescription: jobDescription.trim() || undefined,
      resumeText: resumeText.trim() || undefined,
    });
  }

  return (
    <form className="setup-form" onSubmit={submit}>
      <div className="field">
        <label htmlFor="participant-name">{product.participantLabel}</label>
        <input
          id="participant-name"
          autoComplete="name"
          maxLength={120}
          required
          value={participantName}
          onChange={(event) => setParticipantName(event.target.value)}
          placeholder="Enter a display name"
        />
      </div>

      {product.requiresInterviewContext ? (
        <>
          <div className="field">
            <label htmlFor="job-description">Job description</label>
            <textarea
              id="job-description"
              required
              rows={7}
              value={jobDescription}
              onChange={(event) => setJobDescription(event.target.value)}
              placeholder="Paste the role responsibilities and requirements"
            />
          </div>
          <div className="field">
            <label htmlFor="resume-text">Resume text</label>
            <textarea
              id="resume-text"
              required
              rows={7}
              value={resumeText}
              onChange={(event) => setResumeText(event.target.value)}
              placeholder="Paste the candidate resume text"
            />
          </div>
        </>
      ) : (
        <p className="form-note">
          No account credentials are needed for this internal support demo.
        </p>
      )}

      <button className="button primary" type="submit">
        Continue to device check
      </button>
    </form>
  );
}
