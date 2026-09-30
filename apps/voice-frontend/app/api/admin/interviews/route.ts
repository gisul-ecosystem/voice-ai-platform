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
  const definitionId = (url.searchParams.get("definitionId") || "").trim();
  if (definitionId.length < 8) {
    return NextResponse.json(
      { error: "definitionId is required." },
      { status: 422 },
    );
  }
  const limit = url.searchParams.get("limit") || "50";
  const headers: Record<string, string> = {};
  const token = process.env.BACKEND_SERVICE_TOKEN?.trim();
  if (token) headers.authorization = `Bearer ${token}`;
  try {
    const query = new URLSearchParams({
      definition_id: definitionId,
      limit,
    });
    const response = await fetch(`${backendUrl}/v1/interviews?${query}`, {
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      return NextResponse.json(
        {
          error:
            typeof data.detail === "string"
              ? data.detail
              : "Could not load invites.",
        },
        { status: response.status },
      );
    }
    const items = Array.isArray(data.items) ? data.items : [];
    return NextResponse.json(
      {
        items: items.map((row: Record<string, unknown>) => ({
          interviewId: row.interview_id,
          definitionId: row.definition_id,
          candidateName: row.candidate_name,
          candidateEmail: row.candidate_email,
          status: row.status,
          startsAt: row.starts_at,
          invitationToken: row.invitation_token ?? null,
          candidatePath: row.candidate_path ?? null,
          createdAt: row.created_at ?? null,
        })),
      },
      { headers: { "cache-control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      { error: "Interview service could not be reached." },
      { status: 502 },
    );
  }
}
