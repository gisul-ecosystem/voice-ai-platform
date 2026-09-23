import type { ProductId } from "@/lib/products";

export const INTERVIEW_DURATION_OPTIONS = [15, 30, 45] as const;
export type InterviewDurationMinutes =
  (typeof INTERVIEW_DURATION_OPTIONS)[number];

export function normalizeInterviewDuration(
  value: unknown,
): InterviewDurationMinutes {
  if (value === 15 || value === 30 || value === 45) {
    return value;
  }
  return 30;
}

export type PublicSessionRequest = {
  productId: ProductId;
  participantName: string;
  jobDescription?: string;
  resumeText?: string;
  /** Structured claims from resume ingest; personalizes opening, does not change job bar. */
  candidateProfile?: Record<string, unknown>;
  invitationToken?: string;
  idempotencyKey?: string;
  candidateEmail?: string;
  candidateId?: string;
  candidateProfile?: Record<string, unknown>;
  definitionId?: string;
  startsAt?: string;
  timezone?: string;
  interviewSetup?: {
    title: string;
    role: string;
    seniority: string;
    difficulty: string;
    durationMinutes: InterviewDurationMinutes;
    language: string;
    competencies: string[];
    maxProbesPerPhase: number;
    monitoringEnabled: boolean;
    recordingEnabled: boolean;
  };
};

export type BackendSessionPayload = {
  product_id: ProductId;
  name: string;
  context_id?: string;
  invitation_token?: string;
  idempotency_key?: string;
};

export type SessionCredentials = {
  room: string;
  token: string;
  livekitUrl: string;
  productId: ProductId;
  sessionId?: string;
};

type BackendSessionResponse = {
  room?: unknown;
  token?: unknown;
  livekit_url?: unknown;
  product_id?: unknown;
  session_id?: unknown;
};

export function buildBackendSessionPayload(
  input: PublicSessionRequest,
  contextId?: string,
): BackendSessionPayload {
  const payload: BackendSessionPayload = {
    product_id: input.productId,
    name: input.participantName.trim(),
  };

  if (contextId) payload.context_id = contextId;
  if (input.invitationToken) payload.invitation_token = input.invitationToken;
  if (input.idempotencyKey) payload.idempotency_key = input.idempotencyKey;

  return payload;
}

export function sanitizeSessionResponse(
  value: BackendSessionResponse,
): SessionCredentials {
  if (
    typeof value.room !== "string" ||
    typeof value.token !== "string" ||
    typeof value.livekit_url !== "string" ||
    value.product_id !== "interviewer"
  ) {
    throw new Error("The session service returned an invalid response.");
  }

  const credentials: SessionCredentials = {
    room: value.room,
    token: value.token,
    livekitUrl: value.livekit_url,
    productId: value.product_id,
  };
  if (typeof value.session_id === "string" && value.session_id.trim()) {
    credentials.sessionId = value.session_id.trim();
  }
  return credentials;
}

export function toUserFacingSessionError(status: number, detail?: string): string {
  if (status === 422) return detail || "Check the session details and try again.";
  if (status === 503)
    return "The voice service is not configured. Ask an administrator to check LiveKit settings.";
  if (status >= 500)
    return "The voice service is temporarily unavailable. Try again shortly.";
  return detail || "The session could not be created.";
}
