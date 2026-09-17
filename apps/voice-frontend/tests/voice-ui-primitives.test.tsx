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
  useTranscriptions: () => [
    {
      streamInfo: { id: "candidate-1" },
      participantInfo: { identity: "candidate" },
      text: "I designed the retry strategy.",
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
} from "@gisul/voice-ui";

describe("shared voice UI primitives", () => {
  it("distinguishes partial transcript turns without announcing the entire log", async () => {
    render(<VoiceTranscripts />);

    expect(
      await screen.findByText("I designed the retry strategy."),
    ).toBeInTheDocument();
    expect(screen.getByText("How did you validate it?")).toBeInTheDocument();
    expect(screen.getByText("Speaking…")).toBeInTheDocument();
    expect(
      screen.getByRole("region", { name: "Live interview transcript" }),
    ).toBeInTheDocument();
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
