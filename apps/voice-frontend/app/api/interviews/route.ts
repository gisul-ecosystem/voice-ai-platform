import { NextResponse } from "next/server";

export const runtime = "nodejs";

function publicScheduleError(status: number, detail?: unknown): string {
  if (status === 409) return "This interview has already been scheduled.";
  if (status === 429) return "Too many requests. Wait a moment and try again.";
  if (status === 422) {
    if (typeof detail === "string" && detail.trim()) return detail.trim();
    if (Array.isArray(detail) && detail[0] && typeof detail[0] === "object") {
      const first = detail[0] as { msg?: unknown };
      if (typeof first.msg === "string" && first.msg.trim()) return first.msg.trim();
    }
    return "Review the interview details and try again.";
  }
  return "The interview could not be scheduled.";
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
        candidate_id: body.candidateId,
        starts_at: body.startsAt,
        timezone: body.timezone,
        join_early_minutes: body.joinEarlyMinutes ?? 0,
        late_grace_minutes: body.lateGraceMinutes ?? 43_200,
        job_description: body.jobDescription,
        resume_text: body.resumeText,
        interview_setup: body.interviewSetup,
        definition_id: body.definitionId,
        candidate_profile: body.candidateProfile,
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
          error: publicScheduleError(upstream.status, data.detail),
        },
        { status: upstream.ok ? 502 : upstream.status },
      );
    }
    return NextResponse.json(
      {
        interviewId: data.interview_id,
        invitationToken: data.invitation_token,
          candidatePath: `/interview/invite/${encodeURIComponent(data.invitation_token)}`,
        startsAt: data.starts_at,
          definitionId: data.definition_id,
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
