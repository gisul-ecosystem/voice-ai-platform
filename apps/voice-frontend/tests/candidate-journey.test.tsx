import React, { type ComponentType, type ReactNode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const createVoiceSession = vi.hoisted(() => vi.fn());

vi.mock("next/dynamic", () => ({
  default: (loader: () => Promise<unknown>) => {
    let resolved: ComponentType<any> | null = null;
    const pending = loader().then((mod) => {
      if (typeof mod === "function") {
        resolved = mod as ComponentType<any>;
      } else {
        const record = mod as Record<string, ComponentType<any>>;
        resolved =
          record.default ||
          record.DevicePreJoin ||
          record.LiveInterviewRoom ||
          (Object.values(record)[0] as ComponentType<any>);
      }
      return resolved;
    });
    return function DynamicTestComponent(props: Record<string, unknown>) {
      const [Comp, setComp] = React.useState<ComponentType<any> | null>(
        () => resolved,
      );
      React.useEffect(() => {
        void pending.then((component) => {
          if (component) setComp(() => component);
        });
      }, []);
      if (!Comp) return <div data-testid="dynamic-loading" />;
      return <Comp {...props} />;
    };
  },
}));

vi.mock("@/components/DevicePreJoin", () => ({
  DevicePreJoin: ({
    onSubmit,
    product,
  }: {
    onSubmit: (choices: {
      username: string;
      audioEnabled: boolean;
      videoEnabled: boolean;
    }) => void;
    product: { joinLabel: string };
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
      {`I am ready — ${product.joinLabel}`}
    </button>
  ),
}));

vi.mock("@/components/LiveInterviewRoom", () => ({
  LiveInterviewRoom: () => <div data-testid="voice-room" />,
}));

vi.mock("@gisul/voice-ui/session", () => ({
  createVoiceSession,
}));

vi.mock("@gisul/voice-ui", () => ({
  VoiceAgentStatus: () => null,
  VoiceSessionControls: () => null,
  VoiceTranscripts: () => null,
  VoicePreJoin: () => null,
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

  it("shows a recoverable message when invitation details are incomplete", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ interview_id: "int_bad" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );

    render(<CandidateInterviewJourney invitationToken="bad-token" />);
    expect(
      await screen.findByRole("heading", { name: "Invitation unavailable" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Invitation details were incomplete/i),
    ).toBeInTheDocument();
  });
});
