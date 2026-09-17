import { NextResponse } from "next/server";

export const runtime = "nodejs";

function publicInvitationError(status: number): string {
  if (status === 404) return "This invitation is invalid or no longer available.";
  if (status === 409) return "This invitation has already been used.";
  if (status === 410) return "This invitation has expired.";
  if (status === 422) return "The required consent could not be recorded.";
  if (status === 429) return "Too many requests. Wait a moment and try again.";
  return "Invitation could not be verified.";
}

export async function POST(request: Request) {
  const backendUrl = process.env.BACKEND_API_URL?.replace(/\/+$/, "");
  if (!backendUrl) {
    return NextResponse.json(
      { error: "The interview service is not configured." },
      { status: 503 },
    );
  }
  let body: Record<string, unknown>;
  try {
    body = (await request.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json({ error: "Invalid request." }, { status: 400 });
  }
  if (
    typeof body.invitationToken !== "string" ||
    !body.invitationToken.trim()
  ) {
    return NextResponse.json(
      { error: "Invitation is required." },
      { status: 400 },
    );
  }
  const consent = body.consent;
  const isConsent = consent && typeof consent === "object";
  const path = isConsent
    ? "/v1/candidate/invitations/consent"
    : "/v1/candidate/invitations/preview";
  const payload = isConsent
    ? {
        invitation_token: body.invitationToken,
        ...(consent as Record<string, unknown>),
      }
    : { invitation_token: body.invitationToken };
  try {
    const upstream = await fetch(`${backendUrl}${path}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    if (upstream.status === 204) return new NextResponse(null, { status: 204 });
    const data = await upstream.json().catch(() => ({}));
    if (!upstream.ok) {
      return NextResponse.json(
        { error: publicInvitationError(upstream.status) },
        { status: upstream.status },
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
