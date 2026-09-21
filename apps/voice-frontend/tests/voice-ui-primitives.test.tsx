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
      streamInfo: { id: "c1", timestamp: 200 },
      participantInfo: { identity: "candidate" },
      text: "And we are using VLLM",
    },
    {
      streamInfo: { id: "c2", timestamp: 250 },
      participantInfo: { identity: "candidate" },
      text: "And we are using VLLM and KV",
    },
    {
      // Echo of agent speech wrongly arriving as candidate stream.
      streamInfo: { id: "echo", timestamp: 110 },
      participantInfo: { identity: "candidate" },
      text: "Thanks for joining. I'm your interviewer for this conversation. To get started, please introduce yourself.",
    },
    {
      streamInfo: { id: "a-stream", timestamp: 100 },
      participantInfo: { identity: "worker-aaptor", kind: "AGENT" },
      text: "Thanks for joining. I'm your interviewer for this conversation. To get started, please introduce yourself.",
    },
  ],
  useVoiceAssistant: () => ({
    agent: { identity: "agent" },
    state: "listening",
    agentTranscriptions: [
      {
        id: "agent-open",
        text: "Thanks for joining. I'm your interviewer for this conversation. To get started, please introduce yourself.",
        final: true,
        firstReceivedTime: 100,
        lastReceivedTime: 100,
      },
      {
        id: "agent-1",
        text: "How did you validate it?",
        final: false,
        firstReceivedTime: 300,
        lastReceivedTime: 300,
      },
    ],
  }),
}));

import {
  VoiceSessionControls,
  VoiceTranscripts,
  coalesceTranscriptLines,
  isEchoOfAgentSpeech,
  isLikelyEchoFragment,
} from "@gisul/voice-ui";

describe("shared voice UI primitives", () => {
  it("coalesces growing candidate STT fragments into one line", () => {
    const lines = coalesceTranscriptLines([
      {
        id: "1",
        who: "candidate",
        text: "And we are using VLLM",
        final: true,
        at: 1,
      },
      {
        id: "2",
        who: "candidate",
        text: "And we are using VLLM and KV",
        final: true,
        at: 2,
      },
    ]);
    expect(lines).toHaveLength(1);
    expect(lines[0]?.text).toBe("And we are using VLLM and KV");
  });

  it("drops candidate lines that echo agent speech", () => {
    const agent =
      "Thanks for joining. I'm your interviewer for this conversation. To get started, please introduce yourself.";
    expect(isEchoOfAgentSpeech(agent, [agent])).toBe(true);
    expect(isLikelyEchoFragment("There are many services")).toBe(true);
    const lines = coalesceTranscriptLines([
      { id: "a", who: "agent", text: agent, final: true, at: 1 },
      { id: "c", who: "candidate", text: agent, final: true, at: 2 },
      {
        id: "c-echo",
        who: "candidate",
        text: "There are the factories there are the",
        final: true,
        at: 2.5,
      },
      {
        id: "c2",
        who: "candidate",
        text: "I built APIs at my last company",
        final: true,
        at: 3,
      },
    ]);
    expect(lines.map((line) => line.who)).toEqual(["agent", "candidate"]);
    expect(lines[1]?.text).toContain("built APIs");
  });

  it("keeps chronological order and hides echo duplicates in the panel", async () => {
    render(<VoiceTranscripts />);

    expect(
      await screen.findByText("And we are using VLLM and KV"),
    ).toBeInTheDocument();
    expect(screen.queryByText("And we are using VLLM")).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Thanks for joining. I'm your interviewer for this conversation. To get started, please introduce yourself.",
      ),
    ).toBeInTheDocument();
    // Echo must not create a second identical "You" line.
    expect(
      screen.getAllByText(
        "Thanks for joining. I'm your interviewer for this conversation. To get started, please introduce yourself.",
      ),
    ).toHaveLength(1);
    expect(screen.getByText("How did you validate it?")).toBeInTheDocument();
    expect(screen.getAllByText("AI Interviewer").length).toBeGreaterThan(0);
    expect(screen.getByText("Speaking…")).toBeInTheDocument();

    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("AI Interviewer");
    expect(items[0]).toHaveTextContent("Thanks for joining");
    expect(items[1]).toHaveTextContent("You");
    expect(items[1]).toHaveTextContent("And we are using VLLM and KV");
    expect(items[2]).toHaveTextContent("How did you validate it?");
  });

  it("labels agent streams correctly when the worker identity differs", async () => {
    render(<VoiceTranscripts />);

    expect(
      await screen.findByText(
        "Thanks for joining. I'm your interviewer for this conversation. To get started, please introduce yourself.",
      ),
    ).toBeInTheDocument();
    expect(screen.getAllByText("AI Interviewer").length).toBeGreaterThan(0);
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
