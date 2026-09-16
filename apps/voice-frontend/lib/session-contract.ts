import type { ProductId } from "@/lib/products";

export type PublicSessionRequest = {
  productId: ProductId;
  participantName: string;
  jobDescription?: string;
  resumeText?: string;
};

export type BackendSessionPayload = {
  product_id: ProductId;
  name: string;
  context_id?: string;
};

export type SessionCredentials = {
  room: string;
  token: string;
  livekitUrl: string;
  productId: ProductId;
};

type BackendSessionResponse = {
  room?: unknown;
  token?: unknown;
  livekit_url?: unknown;
  product_id?: unknown;
};

export function buildBackendSessionPayload(
  input: PublicSessionRequest,
  contextId?: string,
): BackendSessionPayload {
  const payload: BackendSessionPayload = {
    product_id: input.productId,
    name: input.participantName.trim(),
  };

  if (input.productId === "interviewer" && contextId)
    payload.context_id = contextId;

  return payload;
}

export function sanitizeSessionResponse(
  value: BackendSessionResponse,
): SessionCredentials {
  if (
    typeof value.room !== "string" ||
    typeof value.token !== "string" ||
    typeof value.livekit_url !== "string" ||
    (value.product_id !== "interviewer" &&
      value.product_id !== "customer-support")
  ) {
    throw new Error("The session service returned an invalid response.");
  }

  return {
    room: value.room,
    token: value.token,
    livekitUrl: value.livekit_url,
    productId: value.product_id,
  };
}

export function toUserFacingSessionError(status: number, detail?: string): string {
  if (status === 422) return detail || "Check the session details and try again.";
  if (status === 503)
    return "The voice service is not configured. Ask an administrator to check LiveKit settings.";
  if (status >= 500)
    return "The voice service is temporarily unavailable. Try again shortly.";
  return detail || "The session could not be created.";
}
