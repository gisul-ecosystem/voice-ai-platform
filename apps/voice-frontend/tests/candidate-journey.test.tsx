import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CandidateInterviewJourney } from "@/components/CandidateInterviewJourney";

describe("scheduled candidate journey", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("verifies invitation and records consent before device access", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            interview_id: "int_test",
            candidate_name: "Priya",
            title: "Backend interview",
            role: "Backend Engineer",
            starts_at: new Date().toISOString(),
            timezone: "Asia/Kolkata",
            duration_minutes: 30,
            join_not_before: new Date(Date.now() - 60_000).toISOString(),
            join_closes_at: new Date(Date.now() + 60_000).toISOString(),
            monitoring_enabled: true,
            recording_enabled: false,
            status: "ready",
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    render(<CandidateInterviewJourney invitationToken="signed-token" />);
    expect(
      await screen.findByRole("heading", { name: "Backend interview" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/conducted by AI/i));
    fireEvent.click(screen.getByLabelText(/agree to transcription/i));
    fireEvent.click(screen.getByLabelText(/listen silently/i));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toMatchObject({
      invitationToken: "signed-token",
      consent: {
        ai_interview: true,
        transcription: true,
        monitoring: true,
      },
    });
  });
});
