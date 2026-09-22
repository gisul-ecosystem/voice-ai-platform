import { afterEach, describe, expect, it, vi } from "vitest";

import { POST } from "@/app/api/brain/ingest/route";

function formRequest(form: FormData): Request {
  return {
    formData: async () => form,
  } as unknown as Request;
}

describe("brain document ingest proxy", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("rejects missing backend configuration", async () => {
    vi.stubEnv("BACKEND_API_URL", "");
    const form = new FormData();
    form.set("kind", "jd");
    form.set("file", new File(["Backend role"], "jd.txt", { type: "text/plain" }));
    const response = await POST(formRequest(form));
    expect(response.status).toBe(503);
  });

  it("forwards multipart ingest and maps camelCase fields", async () => {
    vi.stubEnv("BACKEND_API_URL", "http://backend.test");
    vi.stubEnv("BACKEND_SERVICE_TOKEN", "service-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          kind: "resume",
          filename: "cv.txt",
          content_type: "text",
          page_count: null,
          text: "Projects\n- Billing API",
          warnings: [],
          job_intelligence: null,
          candidate_profile: { projects: [{ text: "Billing API" }] },
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    const form = new FormData();
    form.set("kind", "resume");
    form.set(
      "file",
      new File(["Projects\n- Billing API"], "cv.txt", { type: "text/plain" }),
    );

    const response = await POST(formRequest(form));

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      kind: "resume",
      filename: "cv.txt",
      contentType: "text",
      text: "Projects\n- Billing API",
      candidateProfile: { projects: [{ text: "Billing API" }] },
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://backend.test/interview-brain/documents/ingest",
      expect.objectContaining({
        method: "POST",
      }),
    );
  });

  it("does not leak upstream detail strings for non-422 failures", async () => {
    vi.stubEnv("BACKEND_API_URL", "http://backend.test");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: "secret stack" }), {
          status: 500,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    const form = new FormData();
    form.set("kind", "jd");
    form.set("file", new File(["x"], "jd.txt", { type: "text/plain" }));
    const response = await POST(formRequest(form));
    expect(response.status).toBe(500);
    await expect(response.json()).resolves.toEqual({
      error: "Document ingestion is unavailable.",
    });
  });
});
