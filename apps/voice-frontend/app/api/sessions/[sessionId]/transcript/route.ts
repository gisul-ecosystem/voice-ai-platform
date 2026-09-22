import { NextResponse } from "next/server";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ sessionId: string }>;
};

export async function GET(_request: Request, context: RouteContext) {
  const { sessionId } = await context.params;
  const backendUrl = process.env.BACKEND_API_URL?.replace(/\/+$/, "");
  if (!backendUrl) {
    return NextResponse.json(
      { error: "The interview service is not configured." },
      { status: 503 },
    );
  }
  if (!sessionId || sessionId.length < 8) {
    return NextResponse.json({ error: "Invalid session." }, { status: 422 });
  }

  const serviceToken = process.env.BACKEND_SERVICE_TOKEN?.trim();
  const headers: Record<string, string> = {
    "x-correlation-id": crypto.randomUUID(),
  };
  if (serviceToken) headers.authorization = `Bearer ${serviceToken}`;

  try {
    const upstream = await fetch(
      `${backendUrl}/internal/interview-sessions/${encodeURIComponent(sessionId)}/transcript`,
      {
        method: "GET",
        headers,
        cache: "no-store",
        signal: AbortSignal.timeout(15_000),
      },
    );
    const data = (await upstream.json().catch(() => ({}))) as Record<
      string,
      unknown
    >;
    if (!upstream.ok) {
      return NextResponse.json(
        {
          error:
            upstream.status === 404
              ? "Transcript is not available."
              : "Transcript could not be loaded.",
        },
        { status: upstream.status === 404 ? 404 : 502 },
      );
    }
    return NextResponse.json(data, {
      headers: { "cache-control": "no-store" },
    });
  } catch {
    return NextResponse.json(
      { error: "The interview service could not be reached." },
      { status: 502 },
    );
  }
}
