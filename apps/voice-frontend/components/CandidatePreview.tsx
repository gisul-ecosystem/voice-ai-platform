"use client";

import { useMemo, useState } from "react";

import type { PublicSessionRequest } from "@/lib/session-contract";

type CandidatePreviewProps = {
  request: PublicSessionRequest;
  onBack: () => void;
  onContinue: () => void;
};

export function CandidatePreview({
  request,
  onBack,
  onContinue,
}: CandidatePreviewProps) {
  const setup = request.interviewSetup;
  const [aiConsent, setAiConsent] = useState(false);
  const [transcriptionConsent, setTranscriptionConsent] = useState(false);
  const [monitoringConsent, setMonitoringConsent] = useState(false);
  const [recordingConsent, setRecordingConsent] = useState(false);

  const ready = useMemo(
    () =>
      aiConsent &&
      transcriptionConsent &&
      (!setup?.monitoringEnabled || monitoringConsent) &&
      (!setup?.recordingEnabled || recordingConsent),
    [
      aiConsent,
      monitoringConsent,
      recordingConsent,
      setup,
      transcriptionConsent,
    ],
  );

  if (!setup) return null;

  return (
    <div className="candidate-preview">
      <div className="section-heading">
        <p className="step-label">Candidate preview and consent</p>
        <h2>{setup.title}</h2>
        <p>
          Review how this interview works before granting device permissions.
        </p>
      </div>

      <div className="candidate-summary">
        <dl>
          <div><dt>Role</dt><dd>{setup.role}</dd></div>
          <div><dt>Level</dt><dd>{setup.seniority}</dd></div>
          <div><dt>Duration</dt><dd>{setup.durationMinutes} minutes</dd></div>
          <div><dt>Language</dt><dd>{setup.language}</dd></div>
        </dl>
        <div>
          <h3>What to expect</h3>
          <p>
            An AI interviewer will ask structured, job-related questions. Your
            responses are transcribed and reviewed using defined competencies.
          </p>
          <p>
            Need an accommodation or another assessment format? Contact the
            inviting organization before starting. Requesting support must not
            affect your evaluation.
          </p>
        </div>
      </div>

      <fieldset className="consent-list">
        <legend>Required acknowledgements</legend>
        <label>
          <input type="checkbox" checked={aiConsent}
            onChange={(event) => setAiConsent(event.target.checked)} />
          I understand that this interview is conducted by an AI system.
        </label>
        <label>
          <input type="checkbox" checked={transcriptionConsent}
            onChange={(event) => setTranscriptionConsent(event.target.checked)} />
          I agree to transcription for interview evaluation.
        </label>
        {setup.monitoringEnabled ? (
          <label>
            <input type="checkbox" checked={monitoringConsent}
              onChange={(event) => setMonitoringConsent(event.target.checked)} />
            I understand an authorized human may listen silently.
          </label>
        ) : null}
        {setup.recordingEnabled ? (
          <label>
            <input type="checkbox" checked={recordingConsent}
              onChange={(event) => setRecordingConsent(event.target.checked)} />
            I explicitly agree to audio/video recording.
          </label>
        ) : null}
      </fieldset>

      <div className="setup-actions">
        <button className="button secondary" type="button" onClick={onBack}>
          Back to setup
        </button>
        <button className="button primary" type="button" disabled={!ready}
          onClick={onContinue}>
          Continue to device check
        </button>
      </div>
    </div>
  );
}
