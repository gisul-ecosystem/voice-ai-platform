import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function POST(
  request: Request,
  { params }: { params: Promise<{ candidateId: string }> },
) {
  const backendUrl = process.env.BACKEND_API_URL?.replace(/\/+$/, "");
  if (!backendUrl) return NextResponse.json({ error: "Backend is not configured." }, { status: 503 });
  const { candidateId } = await params;
  const incoming = await request.formData();
  const file = incoming.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "Resume file is required." }, { status: 400 });
  }
  const form = new FormData();
  form.append("file", file, file.name);
  const headers: Record<string, string> = {};
  const token = process.env.BACKEND_SERVICE_TOKEN?.trim();
  if (token) headers.authorization = `Bearer ${token}`;
  try {
    const response = await fetch(
      `${backendUrl}/admin/candidates/${encodeURIComponent(candidateId)}/resume`,
      { method: "POST", headers, body: form, cache: "no-store" },
    );
    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json({ error: "Candidate service could not be reached." }, { status: 502 });
  }
}
