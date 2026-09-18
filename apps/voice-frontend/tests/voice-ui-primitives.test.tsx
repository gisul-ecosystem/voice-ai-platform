import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@livekit/components-react", () => ({
  DisconnectButton: ({ children }: { children: ReactNode }) => (
    <button type="button">{children}</button>
  ),
  LiveKitRoom: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  MediaDeviceMenu: () => <button type="button" aria-label="Choose microphone" />,
  RoomAudioRenderer: () => null,
  TrackToggle: ({ children }: { children: ReactNode }) => (
    <button type="button">{children}</button>
  ),
  VideoTrack: () => null,
  useConnectionState: () => "connected",
  useTracks: () => [],
  useRoomContext: () => ({
    remoteParticipants: new Map(),
    on: () => undefined,
    off: () => undefined,
  }),
  useTranscriptions: () => [
    {
      streamInfo: { id: "c1" },
      participantInfo: { identity: "candidate" },
      text: "And we are using VLLM",
    },
    {
      streamInfo: { id: "c2" },
      participantInfo: { identity: "candidate" },
      text: "And we are using VLLM and KV",
    },
    {
      streamInfo: { id: "a-stream" },
      participantInfo: { identity: "agent" },
      text: "Thanks for joining. I'm your interviewer.",
    },
  ],
  useVoiceAssistant: () => ({
    agent: { identity: "agent" },
    state: "listening",
    agentTranscriptions: [
      {
        id: "agent-1",
        text: "How did you validate it?",
        final: false,
      },
    ],
  }),
}));

import {
  VoiceSessionControls,
  VoiceTranscripts,
  coalesceTranscriptLines,
} from "@gisul/voice-ui";

describe("shared voice UI primitives", () => {
  it("coalesces growing candidate STT fragments into one line", () => {
    const lines = coalesceTranscriptLines([
      {
        id: "1",
        who: "candidate",
        text: "And we are using VLLM",
        final: true,
      },
      {
        id: "2",
        who: "candidate",
        text: "And we are using VLLM and KV",
        final: true,
      },
    ]);
    expect(lines).toHaveLength(1);
    expect(lines[0]?.text).toBe("And we are using VLLM and KV");
  });

  it("distinguishes agent vs candidate and coalesces fragments in the panel", async () => {
    render(<VoiceTranscripts />);

    expect(
      await screen.findByText("And we are using VLLM and KV"),
    ).toBeInTheDocument();
    expect(screen.queryByText("And we are using VLLM")).not.toBeInTheDocument();
    expect(
      screen.getByText("Thanks for joining. I'm your interviewer."),
    ).toBeInTheDocument();
    expect(screen.getByText("How did you validate it?")).toBeInTheDocument();
    expect(screen.getAllByText("AI Interviewer").length).toBeGreaterThan(0);
    expect(screen.getByText("Speaking…")).toBeInTheDocument();
  });

  it("requires confirmation before ending an interview", () => {
    render(<VoiceSessionControls cameraAllowed={false} />);

    fireEvent.click(screen.getByRole("button", { name: "End interview" }));
    expect(screen.getByRole("dialog", { name: "End this interview?" }))
      .toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Continue interview" }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
