import type {
  VoiceSessionCredentials,
  VoiceSessionRequest,
} from "./types";

export async function createVoiceSession(
  request: VoiceSessionRequest,
  endpoint = "/api/sessions",
): Promise<VoiceSessionCredentials> {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(request),
  });
  const data = (await response.json().catch(() => ({}))) as {
    error?: unknown;
  } & Partial<VoiceSessionCredentials>;

  if (!response.ok) {
    throw new Error(
      typeof data.error === "string"
        ? data.error
        : "The voice session could not be created.",
    );
  }
  if (
    typeof data.room !== "string" ||
    typeof data.token !== "string" ||
    typeof data.livekitUrl !== "string" ||
    typeof data.productId !== "string"
  ) {
    throw new Error("The session service returned incomplete credentials.");
  }

  return data as VoiceSessionCredentials;
}
