"use client";

import {
  DisconnectButton,
  LiveKitRoom,
  RoomAudioRenderer,
  TrackToggle,
  VideoTrack,
  useConnectionState,
  useTracks,
  useTranscriptions,
  useVoiceAssistant,
} from "@livekit/components-react";
import { Track } from "livekit-client";
import { useEffect, useState, type ReactNode } from "react";

import type {
  VoiceDeviceChoices,
  VoiceSessionCredentials,
  VoiceSessionLabels,
} from "./types";

export type VoiceRoomProps = {
  credentials: VoiceSessionCredentials;
  choices: VoiceDeviceChoices;
  children: ReactNode;
  className?: string;
  onConnected?: () => void;
  onDisconnected?: () => void;
  onError?: (error: Error) => void;
};

export function VoiceRoom({
  credentials,
  choices,
  children,
  className,
  onConnected,
  onDisconnected,
  onError,
}: VoiceRoomProps) {
  return (
    <LiveKitRoom
      token={credentials.token}
      serverUrl={credentials.livekitUrl}
      connect
      audio={
        choices.audioEnabled ? { deviceId: choices.audioDeviceId } : false
      }
      video={
        choices.videoEnabled ? { deviceId: choices.videoDeviceId } : false
      }
      onConnected={onConnected}
      onDisconnected={onDisconnected}
      onError={onError}
      className={className}
      data-lk-theme="default"
    >
      {children}
    </LiveKitRoom>
  );
}

export function LocalParticipantVideo({
  label = "You",
}: {
  label?: string;
}) {
  const cameraTracks = useTracks([Track.Source.Camera], {
    onlySubscribed: false,
  });
  const localCamera = cameraTracks.find(
    (track) => track.participant.isLocal && track.publication,
  );

  return (
    <section className="video-panel" data-voice-ui="local-video">
      {localCamera ? (
        <VideoTrack trackRef={localCamera} />
      ) : (
        <div className="video-placeholder">
          <span>Camera is off</span>
        </div>
      )}
      <p className="video-label">{label}</p>
    </section>
  );
}

export function VoiceAgentStatus({
  agentName,
  participantLabel = "Voice agent",
  waitingLabel = "Waiting for the worker to join…",
}: {
  agentName: string;
  participantLabel?: string;
  waitingLabel?: string;
}) {
  const { agent, state } = useVoiceAssistant();

  return (
    <section
      className="video-panel agent-panel"
      data-voice-ui="agent-status"
      data-agent-state={state}
    >
      <div className="agent-orb" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <div>
        <strong>{agent ? agentName : "Connecting agent"}</strong>
        <p>{agent ? state : waitingLabel}</p>
      </div>
      <p className="video-label">{participantLabel}</p>
    </section>
  );
}

export function VoiceSessionControls() {
  return (
    <div
      className="session-controls"
      aria-label="Call controls"
      data-voice-ui="controls"
    >
      <TrackToggle source={Track.Source.Microphone}>Microphone</TrackToggle>
      <TrackToggle source={Track.Source.Camera}>Camera</TrackToggle>
      <DisconnectButton>End session</DisconnectButton>
    </div>
  );
}

export function DefaultVoiceSession({
  labels,
}: {
  labels: VoiceSessionLabels;
}) {
  const connectionState = useConnectionState();
  const { agent, state: agentState } = useVoiceAssistant();

  return (
    <div className="live-session" data-voice-ui="default-session">
      <header className="session-header">
        <div>
          <p className="step-label">Live session</p>
          <h2>{labels.title}</h2>
        </div>
        <div className="status-row" aria-live="polite">
          <span className="status-pill">{connectionState}</span>
          <span className="status-pill">
            Agent: {agent ? agentState : "joining"}
          </span>
        </div>
      </header>

      <div className="video-grid">
        <LocalParticipantVideo label={labels.localParticipant} />
        <VoiceAgentStatus
          agentName={labels.agentName}
          participantLabel={labels.agentParticipant}
          waitingLabel={labels.waitingForAgent}
        />
      </div>

      <VoiceTranscripts />
      <RoomAudioRenderer />
      <VoiceSessionControls />
    </div>
  );
}

export function VoiceTranscripts() {
  const streams = useTranscriptions();
  const { agentTranscriptions } = useVoiceAssistant();
  const [lines, setLines] = useState<
    { id: string; who: string; text: string }[]
  >([]);

  useEffect(() => {
    const incoming = [
      ...streams.map((item) => ({
        id: item.streamInfo.id,
        who: item.participantInfo.identity || "you",
        text: item.text.trim(),
      })),
      ...agentTranscriptions.map((segment) => ({
        id: segment.id,
        who: "agent",
        text: segment.text.trim(),
      })),
    ].filter((line) => line.text);
    if (incoming.length === 0) return;
    setLines((current) => {
      const seen = new Set(current.map((line) => `${line.who}:${line.text}`));
      const next = [...current];
      for (const line of incoming) {
        const key = `${line.who}:${line.text}`;
        if (seen.has(key)) continue;
        seen.add(key);
        next.push(line);
      }
      return next;
    });
  }, [streams, agentTranscriptions]);

  return (
    <section className="transcript-panel" data-voice-ui="transcripts">
      <p className="step-label">Transcript</p>
      {lines.length === 0 ? (
        <p className="transcript-empty">
          Speak a full sentence, then pause. Short noise clips are ignored.
        </p>
      ) : (
        <ol className="transcript-list">
          {lines.map((line) => (
            <li key={line.id}>
              <span>{line.who}</span>
              <p>{line.text}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

export type VoiceSessionProps = Omit<VoiceRoomProps, "children"> & {
  labels: VoiceSessionLabels;
  children?: ReactNode;
};

export function VoiceSession({
  labels,
  children,
  ...roomProps
}: VoiceSessionProps) {
  return (
    <VoiceRoom {...roomProps}>
      {children ?? <DefaultVoiceSession labels={labels} />}
    </VoiceRoom>
  );
}
