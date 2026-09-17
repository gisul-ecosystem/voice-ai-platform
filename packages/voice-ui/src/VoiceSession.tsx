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
import { type ReactNode } from "react";

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
      <div className="agent-visual" aria-hidden="true">
        <div className="agent-orb">
          <span />
          <span />
          <span />
          <span />
          <span />
        </div>
      </div>
      <div className="agent-copy">
        <span className="agent-kicker">AI voice agent</span>
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
      <TrackToggle source={Track.Source.Microphone}>
        <span>Microphone</span>
      </TrackToggle>
      <TrackToggle source={Track.Source.Camera}>
        <span>Camera</span>
      </TrackToggle>
      <DisconnectButton>
        <span>End session</span>
      </DisconnectButton>
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
        <div className="session-title">
          <p className="session-live-label">
            <span className="live-dot" aria-hidden="true" />
            Live session
          </p>
          <h2>{labels.title}</h2>
        </div>
        <div className="status-row" aria-live="polite">
          <span className="status-pill">
            Connection <strong>{connectionState}</strong>
          </span>
          <span className="status-pill agent-state-pill">
            Agent <strong>{agent ? agentState : "joining"}</strong>
          </span>
        </div>
      </header>

      <div className="video-grid session-stage">
        <LocalParticipantVideo label={labels.localParticipant} />
        <VoiceAgentStatus
          agentName={labels.agentName}
          participantLabel={labels.agentParticipant}
          waitingLabel={labels.waitingForAgent}
        />
      </div>

      <VoiceTranscripts />
      <RoomAudioRenderer />
      <footer className="session-footer">
        <p>Your audio and video remain in this secure LiveKit room.</p>
        <VoiceSessionControls />
      </footer>
    </div>
  );
}

function isFinalTranscriptFlag(attributes?: Record<string, string>) {
  const value = attributes?.["lk.transcription_final"];
  return value === "true" || value === "1";
}

export function VoiceTranscripts() {
  const streams = useTranscriptions();
  const { agent, agentTranscriptions } = useVoiceAssistant();
  const agentId = agent?.identity;
  const byId = new Map<
    string,
    { id: string; who: string; text: string; at: number }
  >();

  for (const item of streams) {
    if (!isFinalTranscriptFlag(item.streamInfo.attributes)) continue;
    const text = item.text.trim();
    if (!text) continue;
    const isAgent = Boolean(agentId && item.participantInfo.identity === agentId);
    byId.set(item.streamInfo.id, {
      id: item.streamInfo.id,
      who: isAgent ? "agent" : item.participantInfo.identity || "you",
      text,
      at: item.streamInfo.timestamp,
    });
  }

  for (const segment of agentTranscriptions) {
    if (!segment.final) continue;
    const text = segment.text.trim();
    if (!text) continue;
    byId.set(segment.id, {
      id: segment.id,
      who: "agent",
      text,
      at: segment.firstReceivedTime,
    });
  }

  const lines = [...byId.values()].sort((left, right) => left.at - right.at);

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
