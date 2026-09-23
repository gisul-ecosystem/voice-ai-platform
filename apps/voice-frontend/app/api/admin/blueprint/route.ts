import { NextResponse } from "next/server";

export const runtime = "nodejs";

function errorDetail(data: unknown): string | undefined {
  if (!data || typeof data !== "object") return undefined;
  const record = data as Record<string, unknown>;
  if (typeof record.error === "string" && record.error.trim()) return record.error;
  if (typeof record.detail === "string" && record.detail.trim()) return record.detail;
  if (Array.isArray(record.detail)) {
    const parts = record.detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item
          ? String((item as { msg?: string }).msg || "")
          : "",
      )
      .filter(Boolean);
    if (parts.length) return parts.join(" ");
  }
  return undefined;
}

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
    // Extract + LLM competency recommend + compile can exceed 30s.
    signal: AbortSignal.timeout(60_000),
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
      const extractedData = (await extracted.json().catch(() => ({}))) as Record<
        string,
        unknown
      >;
      if (!extracted.ok) {
        return NextResponse.json(
          { error: errorDetail(extractedData) || "JD extraction failed." },
          { status: extracted.status },
        );
      }

      // Authoritative role/seniority from the design form (not JD-inferred only).
      const roleTitle =
        typeof body.role === "string" ? body.role.trim() : "";
      const existingRole =
        extractedData.role && typeof extractedData.role === "object"
          ? (extractedData.role as Record<string, unknown>)
          : {};
      if (roleTitle || body.seniority) {
        extractedData.role = {
          ...existingRole,
          ...(roleTitle ? { title: roleTitle } : {}),
          ...(typeof body.seniority === "string" && body.seniority
            ? { target_level: body.seniority }
            : {}),
        };
      }

      const compiled = await backendRequest("/interview-brain/blueprint/compile", {
        job_intelligence: extractedData,
        title: body.title,
        language: typeof body.language === "string" && body.language.trim() ? body.language : "English",
        timezone: body.timezone || "UTC",
        duration_minutes: body.durationMinutes,
        creator_competencies: body.competencies,
        resume_required: true,
        include_scenarios: true,
      });
      const data = await compiled.json().catch(() => ({}));
      if (!compiled.ok) {
        return NextResponse.json(
          { error: errorDetail(data) || "Alignment generation failed." },
          { status: compiled.status },
        );
      }
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
      if (!published.ok) {
        return NextResponse.json(
          { error: errorDetail(data) || "Publish failed." },
          { status: published.status },
        );
      }
      return NextResponse.json(data, { status: published.status });
    }
    return NextResponse.json({ error: "Unknown blueprint action." }, { status: 400 });
  } catch (reason) {
    const timedOut =
      reason instanceof Error &&
      (reason.name === "TimeoutError" || /aborted|timeout/i.test(reason.message));
    return NextResponse.json(
      {
        error: timedOut
          ? "Blueprint generation timed out. Try again with a shorter JD or retry."
          : "Blueprint service could not be reached.",
      },
      { status: 502 },
    );
  }
}
