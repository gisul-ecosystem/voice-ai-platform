import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET(
  _request: Request,
  context: { params: Promise<{ definitionId: string }> },
) {
  const backendUrl = process.env.BACKEND_API_URL?.replace(/\/+$/, "");
  if (!backendUrl) {
    return NextResponse.json(
      { error: "Backend is not configured." },
      { status: 503 },
    );
  }
  const { definitionId } = await context.params;
  const id = (definitionId || "").trim();
  if (id.length < 8) {
    return NextResponse.json(
      { error: "definitionId is required." },
      { status: 422 },
    );
  }
  const headers: Record<string, string> = {};
  const token = process.env.BACKEND_SERVICE_TOKEN?.trim();
  if (token) headers.authorization = `Bearer ${token}`;
  try {
    const response = await fetch(
      `${backendUrl}/interview-brain/definitions/${encodeURIComponent(id)}`,
      { headers, cache: "no-store", signal: AbortSignal.timeout(15_000) },
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      return NextResponse.json(
        {
          error:
            typeof data.detail === "string"
              ? data.detail
              : "Interview template not found.",
        },
        { status: response.status },
      );
    }
    return NextResponse.json(data, {
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { error: "Blueprint service could not be reached." },
      { status: 502 },
    );
  }
}
