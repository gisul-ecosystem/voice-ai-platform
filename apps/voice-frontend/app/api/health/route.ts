import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const backendUrl = process.env.BACKEND_API_URL?.replace(/\/+$/, "");
  const serviceToken = process.env.BACKEND_SERVICE_TOKEN?.trim();
  if (!backendUrl || !serviceToken) {
    return NextResponse.json(
      { status: "unavailable" },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }

  try {
    const response = await fetch(`${backendUrl}/internal/bff/health`, {
      headers: { authorization: `Bearer ${serviceToken}` },
      cache: "no-store",
      signal: AbortSignal.timeout(5_000),
    });
    const data = (await response.json().catch(() => ({}))) as {
      mongo_connected?: unknown;
    };
    if (!response.ok || data.mongo_connected !== true) {
      return NextResponse.json(
        { status: "unavailable" },
        { status: 503, headers: { "cache-control": "no-store" } },
      );
    }
    return NextResponse.json(
      { status: "ok" },
      { headers: { "cache-control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      { status: "unavailable" },
      { status: 503, headers: { "cache-control": "no-store" } },
    );
  }
}
