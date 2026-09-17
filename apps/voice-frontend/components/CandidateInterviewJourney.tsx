"use client";

import {
  VoiceSession,
  createVoiceSession,
  type VoiceSessionCredentials,
} from "@gisul/voice-ui";
import Link from "next/link";
import { useEffect, useState } from "react";

import {
  DevicePreJoin,
  type DeviceChoices,
} from "@/components/DevicePreJoin";
import { getProduct } from "@/lib/products";

type Preview = {
  interview_id: string;
  candidate_name: string;
  title: string;
  role: string;
  starts_at: string;
  timezone: string;
  duration_minutes: number;
  join_not_before: string;
  join_closes_at: string;
  monitoring_enabled: boolean;
  recording_enabled: boolean;
  status: string;
};

type Stage =
  | "loading"
  | "preview"
  | "prejoin"
  | "connecting"
  | "live"
  | "completed";

export function CandidateInterviewJourney({
  invitationToken,
}: {
  invitationToken: string;
}) {
  const product = getProduct("interviewer");
  const [stage, setStage] = useState<Stage>("loading");
  const [preview, setPreview] = useState<Preview>();
  const [choices, setChoices] = useState<DeviceChoices>();
  const [credentials, setCredentials] = useState<VoiceSessionCredentials>();
  const [error, setError] = useState<string>();
  const [consents, setConsents] = useState({
    ai_interview: false,
    transcription: false,
    monitoring: false,
    recording: false,
  });

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const response = await fetch("/api/invitations", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ invitationToken }),
        });
        const data = (await response.json().catch(() => ({}))) as Preview & {
          error?: string;
        };
        if (!response.ok) throw new Error(data.error || "Invitation is invalid.");
        if (active) {
          setPreview(data);
          setStage("preview");
        }
      } catch (reason) {
        if (active) {
          setError(reason instanceof Error ? reason.message : "Invitation is invalid.");
          setStage("preview");
        }
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [invitationToken]);

  const readyForConsent =
    consents.ai_interview &&
    consents.transcription &&
    (!preview?.monitoring_enabled || consents.monitoring) &&
    (!preview?.recording_enabled || consents.recording);

  async function confirmConsent() {
    if (!preview || !readyForConsent) return;
    setError(undefined);
    try {
      const response = await fetch("/api/invitations", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          invitationToken,
          consent: { ...consents, policy_version: "2026-09-01" },
        }),
      });
      if (!response.ok) {
        const data = (await response.json().catch(() => ({}))) as {
          error?: string;
        };
        throw new Error(data.error || "Consent could not be recorded.");
      }
      setStage("prejoin");
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Consent could not be recorded.",
      );
    }
  }

  async function join(values: DeviceChoices) {
    if (!preview) return;
    setChoices(values);
    setStage("connecting");
    setError(undefined);
    const storageKey = `interview-join:${preview.interview_id}`;
    let idempotencyKey = sessionStorage.getItem(storageKey);
    if (!idempotencyKey) {
      idempotencyKey = crypto.randomUUID();
      sessionStorage.setItem(storageKey, idempotencyKey);
    }
    try {
      setCredentials(
        await createVoiceSession({
          productId: "interviewer",
          participantName: preview.candidate_name,
          invitationToken,
          idempotencyKey,
        }),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The interview room could not be prepared.",
      );
      setStage("prejoin");
    }
  }

  if (stage === "loading") {
    return (
      <div className="center-state" role="status">
        <span className="spinner" aria-hidden="true" />
        <h2>Verifying invitation</h2>
      </div>
    );
  }

  if (!preview) {
    return (
      <div className="center-state">
        <h2>Invitation unavailable</h2>
        <p>{error || "Ask the inviting organization for a new link."}</p>
      </div>
    );
  }

  if (stage === "preview") {
    return (
      <div className="candidate-preview">
        <div className="section-heading">
          <p className="step-label">Candidate invitation</p>
          <h2>{preview.title}</h2>
          <p>Review the interview details and required disclosures.</p>
        </div>
        {error ? <div className="alert" role="alert">{error}</div> : null}
        <div className="candidate-summary">
          <dl>
            <div><dt>Candidate</dt><dd>{preview.candidate_name}</dd></div>
            <div><dt>Role</dt><dd>{preview.role}</dd></div>
            <div><dt>Duration</dt><dd>{preview.duration_minutes} minutes</dd></div>
            <div>
              <dt>Scheduled</dt>
              <dd>{new Date(preview.starts_at).toLocaleString()}</dd>
            </div>
          </dl>
          <div>
            <h3>What to expect</h3>
            <p>
              An AI interviewer asks structured, job-related questions. Only
              finalized transcript evidence should be used for evaluation.
            </p>
            <p>
              For accommodations or an alternative format, contact the inviting
              organization before starting.
            </p>
          </div>
        </div>
        <fieldset className="consent-list">
          <legend>Consent</legend>
          <ConsentCheck label="I understand this interview is conducted by AI."
            checked={consents.ai_interview}
            onChange={(value) => setConsents({ ...consents, ai_interview: value })} />
          <ConsentCheck label="I agree to transcription for evaluation."
            checked={consents.transcription}
            onChange={(value) => setConsents({ ...consents, transcription: value })} />
          {preview.monitoring_enabled ? (
            <ConsentCheck label="I understand an authorized human may listen silently."
              checked={consents.monitoring}
              onChange={(value) => setConsents({ ...consents, monitoring: value })} />
          ) : null}
          {preview.recording_enabled ? (
            <ConsentCheck label="I explicitly agree to interview recording."
              checked={consents.recording}
              onChange={(value) => setConsents({ ...consents, recording: value })} />
          ) : null}
        </fieldset>
        <div className="setup-actions">
          <Link className="button secondary" href="/interviewer">Exit</Link>
          <button className="button primary" type="button"
            disabled={!readyForConsent || preview.status !== "ready"}
            onClick={confirmConsent}>
            {preview.status === "upcoming" ? "Interview is not open yet" : "Continue"}
          </button>
        </div>
      </div>
    );
  }

  if (stage === "prejoin") {
    return (
      <>
        {error ? <div className="alert" role="alert">{error}</div> : null}
        <DevicePreJoin
          product={product}
          participantName={preview.candidate_name}
          onBack={() => setStage("preview")}
          onSubmit={join}
          onError={(reason) => setError(reason.message)}
        />
      </>
    );
  }

  if (stage === "connecting" && !credentials) {
    return (
      <div className="center-state" role="status">
        <span className="spinner" aria-hidden="true" />
        <h2>Preparing your interview room</h2>
        <p>The same request can safely retry if the connection is interrupted.</p>
      </div>
    );
  }

  if ((stage === "connecting" || stage === "live") && credentials && choices) {
    return (
      <VoiceSession
        credentials={credentials}
        choices={choices}
        labels={{
          title: preview.title,
          agentName: "AI Interviewer",
          localParticipant: preview.candidate_name,
          cameraAllowed: product.cameraAllowed,
        }}
        onConnected={() => setStage("live")}
        onDisconnected={() => setStage("completed")}
        onError={(reason) => {
          setError(reason.message);
          setStage("completed");
        }}
      />
    );
  }

  return (
    <div className="center-state completion">
      <span className="completion-mark" aria-hidden="true">✓</span>
      <h2>Interview complete</h2>
      <p>
        Your responses were submitted. The inviting organization will contact
        you after its review process.
      </p>
      {error ? <div className="alert" role="alert">{error}</div> : null}
    </div>
  );
}

function ConsentCheck({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <label>
      <input type="checkbox" checked={checked}
        onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  );
}
