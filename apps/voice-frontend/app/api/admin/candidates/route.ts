import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const backendUrl = process.env.BACKEND_API_URL?.replace(/\/+$/, "");
  if (!backendUrl) return NextResponse.json({ error: "Backend is not configured." }, { status: 503 });
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }
  const headers: Record<string, string> = { "content-type": "application/json" };
  const token = process.env.BACKEND_SERVICE_TOKEN?.trim();
  if (token) headers.authorization = `Bearer ${token}`;
  try {
    const response = await fetch(`${backendUrl}/admin/candidates`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        name: (body as Record<string, unknown>).name,
        email: (body as Record<string, unknown>).email,
        created_by: (body as Record<string, unknown>).createdBy || "reference-demo-admin",
      }),
      cache: "no-store",
    });
    const data = await response.json().catch(() => ({}));
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json({ error: "Candidate service could not be reached." }, { status: 502 });
  }
}
