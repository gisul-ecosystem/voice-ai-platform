"use client";

import {
  Component,
  type ComponentType,
  type ErrorInfo,
  type ReactNode,
  useEffect,
  useRef,
  useState,
} from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import {
  createVoiceSession,
  type VoiceSessionCredentials,
} from "@gisul/voice-ui/session";

import type { DeviceChoices } from "@/components/DevicePreJoin";
import { getProduct } from "@/lib/products";

type LiveInterviewRoomProps = {
  credentials: VoiceSessionCredentials;
  choices: DeviceChoices;
  title: string;
  candidateName: string;
  cameraAllowed: boolean;
  onConnected: () => void;
  onDisconnected: () => void;
  onError: (error: Error) => void;
  onEndRequested: () => void;
};

const DevicePreJoin = dynamic(
  () =>
    import("@/components/DevicePreJoin").then((module) => module.DevicePreJoin),
  {
    ssr: false,
    loading: () => (
      <div className="center-state" role="status">
        <span className="spinner" aria-hidden="true" />
        <h2 tabIndex={-1}>Loading device check</h2>
      </div>
    ),
  },
);

const LiveInterviewRoom = dynamic(
  () =>
    import("@/components/LiveInterviewRoom").then(
      (module) => module.LiveInterviewRoom,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="center-state" role="status">
        <span className="spinner" aria-hidden="true" />
        <h2 tabIndex={-1}>Opening interview room</h2>
      </div>
    ),
  },
) as ComponentType<LiveInterviewRoomProps>;

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
  | "completed"
  | "failed";

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function parsePreview(data: Record<string, unknown>): Preview | undefined {
  const interview_id = asString(data.interview_id);
  const candidate_name = asString(data.candidate_name);
  const title = asString(data.title);
  const role = asString(data.role);
  const starts_at = asString(data.starts_at);
  const timezone = asString(data.timezone) || "UTC";
  const join_not_before = asString(data.join_not_before);
  const join_closes_at = asString(data.join_closes_at);
  const status = asString(data.status) || "unavailable";
  const duration_minutes = Number(data.duration_minutes);
  if (
    !interview_id ||
    !candidate_name ||
    !title ||
    !role ||
    !starts_at ||
    !join_not_before ||
    !join_closes_at ||
    !Number.isFinite(duration_minutes)
  ) {
    return undefined;
  }
  return {
    interview_id,
    candidate_name,
    title,
    role,
    starts_at,
    timezone,
    duration_minutes,
    join_not_before,
    join_closes_at,
    monitoring_enabled: data.monitoring_enabled === true,
    recording_enabled: data.recording_enabled === true,
    status,
  };
}

function invitationStatusMessage(preview: Preview): string | undefined {
  if (preview.status === "upcoming") {
    return "This invitation is not open yet. Try again in a moment.";
  }
  if (preview.status === "expired") {
    return "This invitation has expired. Ask for a new invite link.";
  }
  if (preview.status === "completed") {
    return "This interview has already been completed.";
  }
  if (preview.status !== "ready") {
    return "This invitation is not currently available for joining.";
  }
  return undefined;
}

function newIdempotencyKey(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
}

class JourneyErrorBoundary extends Component<
  { children: ReactNode; onRetry: () => void },
  { message?: string }
> {
  state: { message?: string } = {};

  static getDerivedStateFromError(error: Error) {
    return {
      message:
        error.message || "The interview page hit an unexpected browser error.",
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("candidate_journey_crash", error, info.componentStack);
  }

  render() {
    if (!this.state.message) return this.props.children;
    return (
      <div className="center-state" role="alert" data-candidate-stage="failed">
        <span className="completion-mark" aria-hidden="true">
          !
        </span>
        <h2 tabIndex={-1}>The interview page could not continue</h2>
        <p>{this.state.message}</p>
        <div className="button-row">
          <button
            className="button primary"
            type="button"
            onClick={() => {
              this.setState({ message: undefined });
              this.props.onRetry();
            }}
          >
            Retry interview
          </button>
          <Link className="button secondary" href="/interviewer">
            Return home
          </Link>
        </div>
      </div>
    );
  }
}

function CandidateInterviewJourneyInner({
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
  const joinKey = useRef<string | undefined>(undefined);
  const intentionalDisconnect = useRef(false);
  const becameLive = useRef(false);
  const [consents, setConsents] = useState({
    ai_interview: false,
    transcription: false,
    monitoring: false,
    recording: false,
  });

  async function resolveDisconnectOutcome() {
    if (intentionalDisconnect.current) {
      setStage("completed");
      return;
    }
    const sessionId = credentials?.sessionId;
    if (sessionId) {
      try {
        const response = await fetch(
          `/api/sessions/${encodeURIComponent(sessionId)}/status`,
          { cache: "no-store" },
        );
        const data = (await response.json().catch(() => ({}))) as {
          status?: string;
        };
        if (
          response.ok &&
          (data.status === "completed" || data.status === "completing")
        ) {
          setStage("completed");
          return;
        }
      } catch {
        // Fall through to failed messaging when status is unavailable.
      }
    }
    setError(
      becameLive.current
        ? "The interview room closed before a normal ending. Keep this tab open next time and contact the inviting organization if it happens again."
        : "The room disconnected before the interview was ended. Contact the inviting organization before retrying.",
    );
    setStage("failed");
  }

  useEffect(() => {
    try {
      document
        .querySelector<HTMLElement>("[data-candidate-stage] h2")
        ?.focus({ preventScroll: true });
    } catch {
      // Focus is progressive enhancement only.
    }
  }, [stage]);

  useEffect(() => {
    let active = true;

    async function load() {
      try {
        const response = await fetch("/api/invitations", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ invitationToken }),
        });
        const data = (await response.json().catch(() => ({}))) as Record<
          string,
          unknown
        > & { error?: string };
        if (!response.ok) {
          throw new Error(data.error || "Invitation is invalid.");
        }
        const parsed = parsePreview(data);
        if (!parsed) {
          throw new Error("Invitation details were incomplete.");
        }
        if (active) {
          setPreview(parsed);
          setStage("preview");
        }
      } catch (reason) {
        if (active) {
          setError(
            reason instanceof Error ? reason.message : "Invitation is invalid.",
          );
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
    try {
      const storageKey = `interview-join:${preview.interview_id}`;
      let idempotencyKey = joinKey.current;
      if (!idempotencyKey) {
        try {
          idempotencyKey = sessionStorage.getItem(storageKey) || undefined;
        } catch {
          // Storage can be unavailable in privacy-restricted browser contexts.
        }
      }
      idempotencyKey ||= newIdempotencyKey();
      joinKey.current = idempotencyKey;
      try {
        sessionStorage.setItem(storageKey, idempotencyKey);
      } catch {
        // The in-memory key still makes retries on this page idempotent.
      }
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
      <div className="center-state" role="status" data-candidate-stage="loading">
        <span className="spinner" aria-hidden="true" />
        <h2 tabIndex={-1}>Verifying invitation</h2>
        <p>Checking the signed invitation and interview window.</p>
      </div>
    );
  }

  if (!preview) {
    return (
      <div className="center-state" data-candidate-stage="unavailable">
        <h2 tabIndex={-1}>Invitation unavailable</h2>
        <p>{error || "Ask the inviting organization for a new link."}</p>
        <Link className="button secondary" href="/interviewer">
          Return to AI Interviewer
        </Link>
      </div>
    );
  }

  if (stage === "preview") {
    const statusMessage = invitationStatusMessage(preview);
    return (
      <div className="candidate-preview" data-candidate-stage="preview">
        <div className="section-heading">
          <p className="step-label">Candidate invitation</p>
          <h2 tabIndex={-1}>{preview.title}</h2>
          <p>Review the interview details and required disclosures.</p>
        </div>
        <div className="candidate-preview-body">
          {error ? <div className="alert" role="alert">{error}</div> : null}
          {statusMessage ? (
            <div className="invitation-status" role="status">
              <strong>
                {preview.status === "upcoming" ? "Not ready" : "Unavailable"}
              </strong>
              <p>{statusMessage}</p>
            </div>
          ) : null}
          <div className="candidate-summary">
            <dl>
              <div>
                <dt>Candidate</dt>
                <dd>{preview.candidate_name}</dd>
              </div>
              <div>
                <dt>Role</dt>
                <dd>{preview.role}</dd>
              </div>
              <div>
                <dt>Duration</dt>
                <dd>{preview.duration_minutes} minutes</dd>
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
              <ul className="disclosure-list">
                <li>Live transcription: required</li>
                <li>
                  Silent human monitoring:{" "}
                  {preview.monitoring_enabled ? "enabled" : "not enabled"}
                </li>
                <li>
                  Recording:{" "}
                  {preview.recording_enabled
                    ? "enabled with consent"
                    : "not enabled"}
                </li>
              </ul>
            </div>
          </div>
          <fieldset className="consent-list">
            <legend>Consent</legend>
            <ConsentCheck
              label="I understand this interview is conducted by AI."
              checked={consents.ai_interview}
              onChange={(value) =>
                setConsents({ ...consents, ai_interview: value })
              }
            />
            <ConsentCheck
              label="I agree to transcription for evaluation."
              checked={consents.transcription}
              onChange={(value) =>
                setConsents({ ...consents, transcription: value })
              }
            />
            {preview.monitoring_enabled ? (
              <ConsentCheck
                label="I understand an authorized human may listen silently."
                checked={consents.monitoring}
                onChange={(value) =>
                  setConsents({ ...consents, monitoring: value })
                }
              />
            ) : null}
            {preview.recording_enabled ? (
              <ConsentCheck
                label="I explicitly agree to interview recording."
                checked={consents.recording}
                onChange={(value) =>
                  setConsents({ ...consents, recording: value })
                }
              />
            ) : null}
          </fieldset>
        </div>
        <div className="setup-actions">
          <Link className="button secondary" href="/interviewer">
            Exit
          </Link>
          <button
            className="button primary"
            type="button"
            disabled={!readyForConsent || preview.status !== "ready"}
            onClick={() => void confirmConsent()}
          >
            {preview.status === "ready"
              ? "Continue to audio check"
              : "Joining unavailable"}
          </button>
        </div>
      </div>
    );
  }

  if (stage === "prejoin") {
    return (
      <div data-candidate-stage="prejoin">
        {error ? <div className="alert" role="alert">{error}</div> : null}
        <DevicePreJoin
          product={product}
          participantName={preview.candidate_name}
          onBack={() => setStage("preview")}
          onSubmit={(values) => void join(values)}
          onError={(reason) => setError(reason.message)}
        />
      </div>
    );
  }

  if (stage === "connecting" && !credentials) {
    return (
      <div className="center-state" role="status" data-candidate-stage="connecting">
        <span className="spinner" aria-hidden="true" />
        <h2 tabIndex={-1}>Preparing your interview room</h2>
        <p>The same request can safely retry if the connection is interrupted.</p>
      </div>
    );
  }

  if ((stage === "connecting" || stage === "live") && credentials && choices) {
    return (
      <LiveInterviewRoom
        credentials={credentials}
        choices={choices}
        title={preview.title}
        candidateName={preview.candidate_name}
        cameraAllowed={product.cameraAllowed}
        onConnected={() => {
          intentionalDisconnect.current = false;
          becameLive.current = true;
          setStage("live");
        }}
        onDisconnected={() => {
          void resolveDisconnectOutcome();
        }}
        onError={(reason) => {
          setError(reason.message);
          setStage("failed");
        }}
        onEndRequested={() => {
          intentionalDisconnect.current = true;
        }}
      />
    );
  }

  const failed = stage === "failed";
  return (
    <div className="center-state completion" data-candidate-stage={stage}>
      <span className="completion-mark" aria-hidden="true">
        {failed ? "!" : "✓"}
      </span>
      <h2 tabIndex={-1}>
        {failed ? "Interview disconnected" : "Interview complete"}
      </h2>
      <p>
        {failed
          ? "The room closed unexpectedly. Contact the inviting organization before retrying."
          : "Your responses were submitted. The inviting organization will contact you after its review process."}
      </p>
      {error ? <div className="alert" role="alert">{error}</div> : null}
      <Link className="button secondary" href="/interviewer">
        Return to AI Interviewer
      </Link>
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
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      {label}
    </label>
  );
}

export function CandidateInterviewJourney({
  invitationToken,
}: {
  invitationToken: string;
}) {
  const [resetToken, setResetToken] = useState(0);
  return (
    <JourneyErrorBoundary onRetry={() => setResetToken((value) => value + 1)}>
      <CandidateInterviewJourneyInner
        key={`${invitationToken}:${resetToken}`}
        invitationToken={invitationToken}
      />
    </JourneyErrorBoundary>
  );
}
