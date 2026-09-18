import { describe, expect, it } from "vitest";

import {
  buildBackendSessionPayload,
  sanitizeSessionResponse,
  toUserFacingSessionError,
} from "@/lib/session-contract";

describe("session contract", () => {
  it("builds a secret-free, product-based backend payload", () => {
    const input = {
      productId: "interviewer" as const,
      participantName: "  Priya  ",
      jobDescription: "  Backend engineer  ",
      resumeText: "  Five years  ",
      llm_api_key: "browser-secret",
      agent_name: "aaptor",
    };

    expect(buildBackendSessionPayload(input, "ctx-1234567890123456")).toEqual({
      product_id: "interviewer",
      name: "Priya",
      context_id: "ctx-1234567890123456",
    });
  });

  it("returns only browser-safe response fields", () => {
    const response = sanitizeSessionResponse({
      room: "room-1",
      token: "participant-token",
      livekit_url: "wss://livekit.test",
      product_id: "interviewer",
      llm_api_key: "must-not-leak",
      provider_policy_id: "internal",
    } as never);

    expect(response).toEqual({
      room: "room-1",
      token: "participant-token",
      livekitUrl: "wss://livekit.test",
      productId: "interviewer",
    });
    expect(JSON.stringify(response)).not.toContain("must-not-leak");
  });

  it("maps backend failures to actionable messages", () => {
    expect(toUserFacingSessionError(422, "Unknown product")).toBe(
      "Unknown product",
    );
    expect(toUserFacingSessionError(503)).toContain("not configured");
    expect(toUserFacingSessionError(502)).toContain("temporarily unavailable");
  });
});
