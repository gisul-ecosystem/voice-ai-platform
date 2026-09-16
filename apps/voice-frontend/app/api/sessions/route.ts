import { NextResponse } from "next/server";

import {
  buildBackendSessionPayload,
  sanitizeSessionResponse,
  toUserFacingSessionError,
  type PublicSessionRequest,
} from "@/lib/session-contract";

export const runtime = "nodejs";

function parseRequest(value: unknown): PublicSessionRequest {
  if (!value || typeof value !== "object") {
    throw new Error("A JSON request body is required.");
  }

  const body = value as Record<string, unknown>;
  if (
    body.productId !== "interviewer" &&
    body.productId !== "customer-support"
  ) {
    throw new Error("Choose a supported voice product.");
  }
  if (
    typeof body.participantName !== "string" ||
    !body.participantName.trim()
  ) {
    throw new Error("Participant name is required.");
  }

  return {
    productId: body.productId,
    participantName: body.participantName,
    jobDescription:
      typeof body.jobDescription === "string"
        ? body.jobDescription
        : undefined,
    resumeText:
      typeof body.resumeText === "string" ? body.resumeText : undefined,
  };
}

export async function POST(request: Request) {
  let input: PublicSessionRequest;
  try {
    input = parseRequest(await request.json());
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "The request is invalid.";
    return NextResponse.json({ error: message }, { status: 400 });
  }

  const backendUrl = process.env.BACKEND_API_URL?.replace(/\/+$/, "");
  if (!backendUrl) {
    return NextResponse.json(
      { error: "The frontend session service is not configured." },
      { status: 503 },
    );
  }

  try {
    const serviceToken = process.env.BACKEND_SERVICE_TOKEN?.trim();
    const headers: Record<string, string> = {
      "content-type": "application/json",
      "x-correlation-id": crypto.randomUUID(),
    };
    if (serviceToken) headers.authorization = `Bearer ${serviceToken}`;

    let contextId: string | undefined;
    if (input.productId === "interviewer") {
      const jobDescription = input.jobDescription?.trim();
      const resumeText = input.resumeText?.trim();
      if (!jobDescription || !resumeText) {
        return NextResponse.json(
          { error: "Job description and resume are required." },
          { status: 400 },
        );
      }
      const contextResponse = await fetch(`${backendUrl}/interview-contexts`, {
        method: "POST",
        headers,
        body: JSON.stringify({
          job_description: jobDescription,
          resume_text: resumeText,
        }),
        cache: "no-store",
        signal: AbortSignal.timeout(15_000),
      });
      const context = (await contextResponse.json().catch(() => ({}))) as Record<
        string,
        unknown
      >;
      if (!contextResponse.ok || typeof context.context_id !== "string") {
        return NextResponse.json(
          { error: "The interview context could not be prepared." },
          { status: contextResponse.ok ? 502 : contextResponse.status },
        );
      }
      contextId = context.context_id;
    }

    const upstream = await fetch(`${backendUrl}/sessions/token`, {
      method: "POST",
      headers,
      body: JSON.stringify(buildBackendSessionPayload(input, contextId)),
      cache: "no-store",
      signal: AbortSignal.timeout(15_000),
    });
    const data = (await upstream.json().catch(() => ({}))) as Record<
      string,
      unknown
    >;

    if (!upstream.ok) {
      const detail = typeof data.detail === "string" ? data.detail : undefined;
      return NextResponse.json(
        { error: toUserFacingSessionError(upstream.status, detail) },
        { status: upstream.status },
      );
    }

    return NextResponse.json(sanitizeSessionResponse(data), {
      headers: { "cache-control": "no-store" },
    });
  } catch (error) {
    const message =
      error instanceof Error && error.name === "AbortError"
        ? "The voice service timed out. Try again."
        : "The voice service could not be reached.";
    return NextResponse.json({ error: message }, { status: 502 });
  }
}
