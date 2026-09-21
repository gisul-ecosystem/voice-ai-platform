import { NextResponse } from "next/server";

export const runtime = "nodejs";

async function backendRequest(path: string, body: unknown) {
  const backendUrl = process.env.BACKEND_API_URL?.replace(/\/+$/, "");
  if (!backendUrl) throw new Error("Backend is not configured.");
  const headers: Record<string, string> = { "content-type": "application/json" };
  const token = process.env.BACKEND_SERVICE_TOKEN?.trim();
  if (token) headers.authorization = `Bearer ${token}`;
  return fetch(`${backendUrl}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    cache: "no-store",
    signal: AbortSignal.timeout(30_000),
  });
}

export async function POST(request: Request) {
  const body = (await request.json().catch(() => null)) as Record<string, unknown> | null;
  if (!body || typeof body.action !== "string") {
    return NextResponse.json({ error: "Invalid blueprint request." }, { status: 400 });
  }
  try {
    if (body.action === "compile") {
      const extracted = await backendRequest("/interview-brain/jd/extract", {
        job_description: body.jobDescription,
        target_level: body.seniority,
      });
      const extractedData = await extracted.json().catch(() => ({}));
      if (!extracted.ok) return NextResponse.json({ error: extractedData.detail || "JD extraction failed." }, { status: extracted.status });
      const compiled = await backendRequest("/interview-brain/blueprint/compile", {
        job_intelligence: extractedData,
        title: body.title,
        language: "English",
        timezone: body.timezone || "UTC",
        duration_minutes: body.durationMinutes,
        creator_competencies: body.competencies,
        resume_required: true,
        include_scenarios: true,
      });
      const data = await compiled.json().catch(() => ({}));
      return NextResponse.json(data, { status: compiled.status });
    }
    if (body.action === "publish") {
      const draft = body.draft && typeof body.draft === "object"
        ? { ...(body.draft as Record<string, unknown>) }
        : {};
      const jobIntelligence = draft.job_intelligence;
      if (jobIntelligence && typeof jobIntelligence === "object") {
        draft.job_intelligence = {
          ...(jobIntelligence as Record<string, unknown>),
          approved: true,
          approved_at: new Date().toISOString(),
        };
      }
      if (Array.isArray(draft.scenario_bank)) {
        draft.scenario_bank = draft.scenario_bank.map((scenario) =>
          scenario && typeof scenario === "object" &&
          (scenario as Record<string, unknown>).source === "ai_generated"
            ? { ...(scenario as Record<string, unknown>), approved: true }
            : scenario,
        );
      }
      const published = await backendRequest("/interview-brain/blueprint/publish", {
        draft,
        published_by: body.publishedBy || "reference-demo-admin",
        definition_id: body.definitionId,
        version: 1,
      });
      const data = await published.json().catch(() => ({}));
      return NextResponse.json(data, { status: published.status });
    }
    return NextResponse.json({ error: "Unknown blueprint action." }, { status: 400 });
  } catch {
    return NextResponse.json({ error: "Blueprint service could not be reached." }, { status: 502 });
  }
}
