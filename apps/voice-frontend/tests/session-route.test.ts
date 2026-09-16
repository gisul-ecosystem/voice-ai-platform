import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/sessions/route";

describe("same-origin session proxy", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("forwards only allowlisted fields and sanitizes the response", async () => {
    vi.stubEnv("BACKEND_API_URL", "http://backend.test/");
    const upstreamFetch = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            context_id: "ctx-1234567890123456",
            expires_at: "2026-09-17T00:00:00Z",
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            room: "room-1",
            token: "token-1",
            livekit_url: "wss://livekit.test",
            product_id: "interviewer",
            llm_api_key: "server-secret",
            provider_policy_id: "internal-policy",
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", upstreamFetch);

    const response = await POST(
      new Request("http://frontend.test/api/sessions", {
        method: "POST",
        body: JSON.stringify({
          productId: "interviewer",
          participantName: "Priya",
          jobDescription: "Backend role",
          resumeText: "Python",
          llm_api_key: "browser-secret",
          agent_name: "aaptor",
        }),
      }),
    );

    expect(response.status).toBe(200);
    expect(upstreamFetch).toHaveBeenCalledTimes(2);
    const contextPayload = JSON.parse(upstreamFetch.mock.calls[0][1].body);
    expect(contextPayload).toEqual({
      job_description: "Backend role",
      resume_text: "Python",
    });
    const forwarded = JSON.parse(upstreamFetch.mock.calls[1][1].body);
    expect(forwarded).toMatchObject({
      product_id: "interviewer",
      name: "Priya",
      context_id: "ctx-1234567890123456",
    });
    expect(forwarded).not.toHaveProperty("agent_name");
    expect(forwarded).not.toHaveProperty("llm_api_key");
    await expect(response.json()).resolves.toEqual({
      room: "room-1",
      token: "token-1",
      livekitUrl: "wss://livekit.test",
      productId: "interviewer",
    });
  });

  it("rejects unknown products before calling FastAPI", async () => {
    const upstreamFetch = vi.fn();
    vi.stubGlobal("fetch", upstreamFetch);

    const response = await POST(
      new Request("http://frontend.test/api/sessions", {
        method: "POST",
        body: JSON.stringify({
          productId: "unknown",
          participantName: "Priya",
        }),
      }),
    );

    expect(response.status).toBe(400);
    expect(upstreamFetch).not.toHaveBeenCalled();
  });
});
