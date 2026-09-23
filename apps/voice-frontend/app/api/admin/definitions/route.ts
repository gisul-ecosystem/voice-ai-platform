import { NextResponse } from "next/server";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const backendUrl = process.env.BACKEND_API_URL?.replace(/\/+$/, "");
  if (!backendUrl) {
    return NextResponse.json(
      { error: "Backend is not configured." },
      { status: 503 },
    );
  }
  const url = new URL(request.url);
  const limit = url.searchParams.get("limit") || "50";
  const headers: Record<string, string> = {};
  const token = process.env.BACKEND_SERVICE_TOKEN?.trim();
  if (token) headers.authorization = `Bearer ${token}`;
  try {
    const response = await fetch(
      `${backendUrl}/interview-brain/definitions?limit=${encodeURIComponent(limit)}`,
      { headers, cache: "no-store", signal: AbortSignal.timeout(15_000) },
    );
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      return NextResponse.json(
        { error: data.detail || "Could not load saved interviews." },
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
