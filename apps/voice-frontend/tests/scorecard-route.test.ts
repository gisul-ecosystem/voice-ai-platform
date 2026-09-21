import { afterEach, describe, expect, it, vi } from "vitest";

import { GET, POST } from "@/app/api/sessions/[sessionId]/scorecard/route";

const context = { params: Promise.resolve({ sessionId: "ses_review01" }) };

describe("scorecard review proxy", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("loads a scorecard from the backend", async () => {
    vi.stubEnv("BACKEND_API_URL", "http://backend.test/");
    vi.stubEnv("BACKEND_SERVICE_TOKEN", "service-token");
    const upstreamFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "ses_review01",
          human_review_status: "pending",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", upstreamFetch);

    const response = await GET(new Request("http://frontend.test/api/sessions/ses_review01/scorecard"), context);
    expect(response.status).toBe(200);
    expect(upstreamFetch).toHaveBeenCalledTimes(1);
    expect(String(upstreamFetch.mock.calls[0][0])).toContain("/scorecard");
    await expect(response.json()).resolves.toMatchObject({
      session_id: "ses_review01",
      human_review_status: "pending",
    });
  });

  it("requires a reason before forwarding an override", async () => {
    vi.stubEnv("BACKEND_API_URL", "http://backend.test");
    const upstreamFetch = vi.fn();
    vi.stubGlobal("fetch", upstreamFetch);

    const response = await POST(
      new Request("http://frontend.test/api/sessions/ses_review01/scorecard", {
        method: "POST",
        body: JSON.stringify({
          status: "overridden",
          reviewer_id: "recruiter@example.com",
        }),
      }),
      context,
    );

    expect(response.status).toBe(422);
    expect(upstreamFetch).not.toHaveBeenCalled();
    await expect(response.json()).resolves.toEqual({
      error: "A reason is required to override this scorecard.",
    });
  });

  it("forwards an override with a reason", async () => {
    vi.stubEnv("BACKEND_API_URL", "http://backend.test");
    vi.stubEnv("BACKEND_SERVICE_TOKEN", "service-token");
    const upstreamFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          session_id: "ses_review01",
          human_review_status: "overridden",
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", upstreamFetch);

    const response = await POST(
      new Request("http://frontend.test/api/sessions/ses_review01/scorecard", {
        method: "POST",
        body: JSON.stringify({
          status: "overridden",
          reviewer_id: "recruiter@example.com",
          override_reason: "Transcript shows ownership the model missed.",
        }),
      }),
      context,
    );

    expect(response.status).toBe(200);
    expect(upstreamFetch).toHaveBeenCalledTimes(1);
    expect(String(upstreamFetch.mock.calls[0][0])).toContain("/scorecard/review");
    expect(JSON.parse(upstreamFetch.mock.calls[0][1].body)).toEqual({
      status: "overridden",
      reviewer_id: "recruiter@example.com",
      override_reason: "Transcript shows ownership the model missed.",
    });
  });

  it("preserves a 422 from the review API", async () => {
    vi.stubEnv("BACKEND_API_URL", "http://backend.test");
    const upstreamFetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ detail: "override_reason is required when status is overridden" }),
        { status: 422, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", upstreamFetch);

    const response = await POST(
      new Request("http://frontend.test/api/sessions/ses_review01/scorecard", {
        method: "POST",
        body: JSON.stringify({
          status: "approved",
          reviewer_id: "recruiter@example.com",
        }),
      }),
      context,
    );

    expect(response.status).toBe(422);
    await expect(response.json()).resolves.toEqual({
      error: "override_reason is required when status is overridden",
    });
  });
});
