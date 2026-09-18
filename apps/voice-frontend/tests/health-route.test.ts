import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "@/app/api/health/route";

describe("deployment health route", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("fails when server-side integration settings are missing", async () => {
    vi.stubEnv("BACKEND_API_URL", "");
    vi.stubEnv("BACKEND_SERVICE_TOKEN", "");

    expect((await GET()).status).toBe(503);
  });

  it("verifies backend authentication and Mongo connectivity", async () => {
    vi.stubEnv("BACKEND_API_URL", "http://backend.test/");
    vi.stubEnv("BACKEND_SERVICE_TOKEN", "service-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ mongo_connected: true }), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    expect((await GET()).status).toBe(200);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://backend.test/internal/bff/health",
      expect.objectContaining({
        headers: { authorization: "Bearer service-token" },
      }),
    );
  });
});
