import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/invitations/route";

describe("invitation proxy", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("does not allow consent fields to replace the validated invitation", async () => {
    vi.stubEnv("BACKEND_API_URL", "http://backend.test");
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    const response = await POST(
      new Request("http://frontend.test/api/invitations", {
        method: "POST",
        body: JSON.stringify({
          invitationToken: "signed-outer-token",
          consent: {
            invitation_token: "attacker-token",
            ai_interview: true,
            transcription: true,
            monitoring: false,
            recording: false,
            policy_version: "2026-09-01",
            unexpected: "discard me",
          },
        }),
      }),
    );

    expect(response.status).toBe(204);
    const forwarded = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(forwarded).toEqual({
      invitation_token: "signed-outer-token",
      ai_interview: true,
      transcription: true,
      monitoring: false,
      recording: false,
      policy_version: "2026-09-01",
    });
  });
});
