import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

const createVoiceSession = vi.hoisted(() => vi.fn());

vi.mock("@livekit/components-react", () => ({
  RoomAudioRenderer: () => null,
  useConnectionQualityIndicator: () => ({ quality: "excellent" }),
  useConnectionState: () => "connected",
}));

vi.mock("@gisul/voice-ui", () => ({
  createVoiceSession,
  VoiceAgentStatus: () => null,
  VoiceSessionControls: () => null,
  VoiceTranscripts: () => null,
  VoicePreJoin: ({
    onSubmit,
    joinLabel,
  }: {
    onSubmit: (choices: {
      username: string;
      audioEnabled: boolean;
      videoEnabled: boolean;
    }) => void;
    joinLabel: string;
  }) => (
    <button
      type="button"
      onClick={() =>
        onSubmit({
          username: "Priya",
          audioEnabled: true,
          videoEnabled: false,
        })
      }
    >
      {joinLabel}
    </button>
  ),
  VoiceRoom: ({ children }: { children: ReactNode }) => (
    <div data-testid="voice-room">{children}</div>
  ),
}));

import { CandidateInterviewJourney } from "@/components/CandidateInterviewJourney";

describe("scheduled candidate journey", () => {
  afterEach(() => {
    createVoiceSession.mockReset();
    vi.unstubAllGlobals();
  });

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
    fireEvent.click(
      screen.getByRole("button", { name: "Continue to audio check" }),
    );

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

  it("explains an upcoming invitation without allowing consent to continue", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            interview_id: "int_future",
            candidate_name: "Priya",
            title: "Backend interview",
            role: "Backend Engineer",
            starts_at: new Date(Date.now() + 3_600_000).toISOString(),
            timezone: "UTC",
            duration_minutes: 30,
            join_not_before: new Date(Date.now() + 3_000_000).toISOString(),
            join_closes_at: new Date(Date.now() + 5_400_000).toISOString(),
            monitoring_enabled: false,
            recording_enabled: false,
            status: "upcoming",
          }),
          { status: 200, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    render(<CandidateInterviewJourney invitationToken="future-token" />);

    expect(await screen.findByText(/This interview opens/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Joining unavailable" }),
    ).toBeDisabled();
  });

  it("creates the voice room after the candidate confirms audio readiness", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce(
          new Response(
            JSON.stringify({
              interview_id: "int_test",
              candidate_name: "Priya",
              title: "Backend interview",
              role: "Backend Engineer",
              starts_at: new Date().toISOString(),
              timezone: "UTC",
              duration_minutes: 30,
              join_not_before: new Date(Date.now() - 60_000).toISOString(),
              join_closes_at: new Date(Date.now() + 60_000).toISOString(),
              monitoring_enabled: false,
              recording_enabled: false,
              status: "ready",
            }),
            { status: 200, headers: { "content-type": "application/json" } },
          ),
        )
        .mockResolvedValueOnce(new Response(null, { status: 204 })),
    );
    createVoiceSession.mockResolvedValue({
      room: "room-test",
      token: "token-test",
      livekitUrl: "wss://livekit.test",
      productId: "interviewer",
    });

    render(<CandidateInterviewJourney invitationToken="signed-token" />);
    await screen.findByRole("heading", { name: "Backend interview" });
    fireEvent.click(screen.getByLabelText(/conducted by AI/i));
    fireEvent.click(screen.getByLabelText(/agree to transcription/i));
    fireEvent.click(
      screen.getByRole("button", { name: "Continue to audio check" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /I am ready/i }),
    );

    expect(await screen.findByTestId("voice-room")).toBeInTheDocument();
    expect(createVoiceSession).toHaveBeenCalledWith(
      expect.objectContaining({
        productId: "interviewer",
        participantName: "Priya",
        invitationToken: "signed-token",
      }),
    );
  });
});
