import { NextResponse } from "next/server";

export const runtime = "nodejs";

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

  const serviceToken = process.env.BACKEND_SERVICE_TOKEN?.trim();
  const headers: Record<string, string> = {
    "content-type": "application/json",
    "x-correlation-id": crypto.randomUUID(),
  };
  if (serviceToken) headers.authorization = `Bearer ${serviceToken}`;

  try {
    const upstream = await fetch(`${backendUrl}/v1/interviews`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        source_product_id: "reference-demo",
        external_interview_id:
          typeof body.externalInterviewId === "string" &&
          body.externalInterviewId.trim()
            ? body.externalInterviewId.trim()
            : `demo_${crypto.randomUUID()}`,
        candidate_name: body.candidateName,
        candidate_email: body.candidateEmail,
        starts_at: body.startsAt,
        timezone: body.timezone,
        join_early_minutes: body.joinEarlyMinutes ?? 15,
        late_grace_minutes: body.lateGraceMinutes ?? 15,
        job_description: body.jobDescription,
        resume_text: body.resumeText,
        interview_setup: body.interviewSetup,
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
    const data = (await upstream.json().catch(() => ({}))) as Record<
      string,
      unknown
    >;
    if (!upstream.ok || typeof data.invitation_token !== "string") {
      return NextResponse.json(
        {
          error:
            typeof data.detail === "string"
              ? data.detail
              : "The interview could not be scheduled.",
        },
        { status: upstream.ok ? 502 : upstream.status },
      );
    }
    return NextResponse.json(
      {
        interviewId: data.interview_id,
        invitationToken: data.invitation_token,
        candidatePath: `/interviewer/attend?invitation=${encodeURIComponent(data.invitation_token)}`,
        startsAt: data.starts_at,
      },
      { headers: { "cache-control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      { error: "The interview service could not be reached." },
      { status: 502 },
    );
  }
}
