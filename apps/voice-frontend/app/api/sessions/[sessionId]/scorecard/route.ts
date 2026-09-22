import { NextResponse } from "next/server";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ sessionId: string }>;
};

function upstreamError(data: Record<string, unknown>, fallback: string) {
  const detail = data.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  const error = data.error;
  if (typeof error === "string" && error.trim()) return error;
  return fallback;
}

function statusForUpstream(status: number) {
  if (status === 404 || status === 409 || status === 422) return status;
  return 502;
}

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
      `${backendUrl}/internal/interview-sessions/${encodeURIComponent(sessionId)}/scorecard`,
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
              ? "Scorecard is not available yet."
              : upstreamError(data, "Scorecard could not be loaded."),
        },
        { status: statusForUpstream(upstream.status) },
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

export async function POST(request: Request, context: RouteContext) {
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

  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json({ error: "Review details are required." }, { status: 422 });
  }

  const status = String(body.status || "").trim();
  const reviewerId = String(body.reviewer_id || "").trim();
  const overrideReason = String(body.override_reason || "").trim();
  if (status !== "approved" && status !== "overridden") {
    return NextResponse.json({ error: "Choose approve or override." }, { status: 422 });
  }
  if (!reviewerId) {
    return NextResponse.json({ error: "Reviewer is required." }, { status: 422 });
  }
  if (status === "overridden" && overrideReason.length < 2) {
    return NextResponse.json(
      { error: "A reason is required to override this scorecard." },
      { status: 422 },
    );
  }

  const payload: Record<string, unknown> = {
    status,
    reviewer_id: reviewerId,
  };
  if (status === "overridden") payload.override_reason = overrideReason;

  const serviceToken = process.env.BACKEND_SERVICE_TOKEN?.trim();
  const headers: Record<string, string> = {
    "content-type": "application/json",
    "x-correlation-id": crypto.randomUUID(),
  };
  if (serviceToken) headers.authorization = `Bearer ${serviceToken}`;

  try {
    const upstream = await fetch(
      `${backendUrl}/internal/interview-sessions/${encodeURIComponent(sessionId)}/scorecard/review`,
      {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
        cache: "no-store",
        signal: AbortSignal.timeout(15_000),
      },
    );
    const data = (await upstream.json().catch(() => ({}))) as Record<string, unknown>;
    if (!upstream.ok) {
      const mapped = statusForUpstream(upstream.status);
      return NextResponse.json(
        {
          error:
            mapped === 404
              ? "Scorecard is not available yet."
              : upstreamError(data, "The review could not be saved."),
        },
        { status: mapped },
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
