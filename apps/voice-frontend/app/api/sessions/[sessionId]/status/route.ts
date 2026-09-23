import { NextResponse } from "next/server";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ sessionId: string }>;
};

/** BFF: session lifecycle status for candidate completion detection. */
export async function GET(_request: Request, context: RouteContext) {
  const { sessionId } = await context.params;
  if (!sessionId || sessionId.length < 8) {
    return NextResponse.json({ error: "Invalid session." }, { status: 422 });
  }

  const backendUrl = process.env.BACKEND_API_URL?.replace(/\/+$/, "");
  if (!backendUrl) {
    return NextResponse.json(
      { error: "Backend is not configured." },
      { status: 503 },
    );
  }

  const serviceToken = process.env.BACKEND_SERVICE_TOKEN?.trim();
  const headers: Record<string, string> = {
    "x-correlation-id": crypto.randomUUID(),
  };
  if (serviceToken) headers.authorization = `Bearer ${serviceToken}`;

  try {
    const upstream = await fetch(
      `${backendUrl}/internal/interview-sessions/${encodeURIComponent(sessionId)}/status`,
      { headers, cache: "no-store", signal: AbortSignal.timeout(10_000) },
    );
    const data = (await upstream.json().catch(() => ({}))) as Record<
      string,
      unknown
    >;
    if (!upstream.ok) {
      return NextResponse.json(
        {
          error:
            typeof data.detail === "string"
              ? data.detail
              : "Session status unavailable.",
        },
        { status: upstream.status },
      );
    }
    return NextResponse.json(data, {
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { error: "Session status could not be reached." },
      { status: 502 },
    );
  }
}
