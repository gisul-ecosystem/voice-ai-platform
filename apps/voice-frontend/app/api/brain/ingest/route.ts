import { NextResponse } from "next/server";

export const runtime = "nodejs";

const MAX_UPLOAD_BYTES = 2 * 1024 * 1024;

function publicIngestError(status: number, detail?: string): string {
  if (status === 422) {
    return detail?.trim() || "The document could not be processed.";
  }
  if (status === 429) return "Too many requests. Wait a moment and try again.";
  return "Document ingestion is unavailable.";
}

export async function POST(request: Request) {
  const backendUrl = process.env.BACKEND_API_URL?.replace(/\/+$/, "");
  if (!backendUrl) {
    return NextResponse.json(
      { error: "The interview service is not configured." },
      { status: 503 },
    );
  }

  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return NextResponse.json({ error: "Invalid upload." }, { status: 400 });
  }

  const kind = String(form.get("kind") || "").trim().toLowerCase();
  if (kind !== "jd" && kind !== "resume") {
    return NextResponse.json(
      { error: "Upload kind must be jd or resume." },
      { status: 422 },
    );
  }

  const file = form.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "A file is required." }, { status: 422 });
  }
  if (file.size <= 0 || file.size > MAX_UPLOAD_BYTES) {
    return NextResponse.json(
      { error: "File must be between 1 byte and 2MB." },
      { status: 422 },
    );
  }

  const upstreamForm = new FormData();
  upstreamForm.set("kind", kind);
  upstreamForm.set("file", file, file.name || "upload");
  const targetLevel = form.get("target_level");
  const domain = form.get("domain");
  if (typeof targetLevel === "string" && targetLevel.trim()) {
    upstreamForm.set("target_level", targetLevel.trim());
  }
  if (typeof domain === "string" && domain.trim()) {
    upstreamForm.set("domain", domain.trim());
  }

  const serviceToken = process.env.BACKEND_SERVICE_TOKEN?.trim();
  const headers: Record<string, string> = {
    "x-correlation-id": crypto.randomUUID(),
  };
  if (serviceToken) headers.authorization = `Bearer ${serviceToken}`;

  try {
    const upstream = await fetch(`${backendUrl}/interview-brain/documents/ingest`, {
      method: "POST",
      headers,
      body: upstreamForm,
      cache: "no-store",
      signal: AbortSignal.timeout(30_000),
    });
    const data = (await upstream.json().catch(() => ({}))) as Record<
      string,
      unknown
    >;
    if (!upstream.ok) {
      const detail =
        typeof data.detail === "string"
          ? data.detail
          : Array.isArray(data.detail)
            ? String(
                (data.detail as Array<{ msg?: string }>)
                  .map((item) => item.msg)
                  .filter(Boolean)
                  .join(" "),
              )
            : undefined;
      return NextResponse.json(
        { error: publicIngestError(upstream.status, detail) },
        { status: upstream.status === 422 ? 422 : upstream.ok ? 502 : upstream.status },
      );
    }
    return NextResponse.json(
      {
        kind: data.kind,
        filename: data.filename,
        contentType: data.content_type,
        pageCount: data.page_count ?? null,
        text: data.text,
        warnings: Array.isArray(data.warnings) ? data.warnings : [],
        jobIntelligence: data.job_intelligence ?? null,
        candidateProfile: data.candidate_profile ?? null,
      },
      { headers: { "cache-control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      { error: "The interview service could not be reached." },
      { status: 502 },
    );
  }
}
