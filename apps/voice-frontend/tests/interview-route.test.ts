import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/interviews/route";

describe("interview scheduling proxy", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("does not expose an upstream internal error", async () => {
    vi.stubEnv("BACKEND_API_URL", "http://backend.test");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: "MongoServerError: duplicate key contains private values",
          }),
          { status: 500, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    const response = await POST(
      new Request("http://frontend.test/api/interviews", {
        method: "POST",
        body: JSON.stringify({ candidateName: "Priya" }),
      }),
    );

    expect(response.status).toBe(500);
    await expect(response.json()).resolves.toEqual({
      error: "The interview could not be scheduled.",
    });
  });
});
