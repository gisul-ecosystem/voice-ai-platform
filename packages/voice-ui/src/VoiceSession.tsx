"use client";

import {
  DisconnectButton,
  LiveKitRoom,
  MediaDeviceMenu,
  RoomAudioRenderer,
  TrackToggle,
  VideoTrack,
  useConnectionState,
  useTracks,
  useTranscriptions,
  useVoiceAssistant,
  useRoomContext,
} from "@livekit/components-react";
import { Track, RoomEvent } from "livekit-client";
import { useEffect, useRef, useState, type ReactNode } from "react";

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

function useInterviewerLiveState(voiceAssistantState: string) {
  const room = useRoomContext();
  const { agent } = useVoiceAssistant();
  const [remoteCount, setRemoteCount] = useState(
    () => room.remoteParticipants.size,
  );
  const [remoteSpeaking, setRemoteSpeaking] = useState(false);

  useEffect(() => {
    const refresh = () => {
      const remotes = [...room.remoteParticipants.values()];
      setRemoteCount(remotes.length);
      setRemoteSpeaking(remotes.some((participant) => participant.isSpeaking));
    };
    refresh();
    room.on(RoomEvent.ParticipantConnected, refresh);
    room.on(RoomEvent.ParticipantDisconnected, refresh);
    room.on(RoomEvent.ActiveSpeakersChanged, refresh);
    return () => {
      room.off(RoomEvent.ParticipantConnected, refresh);
      room.off(RoomEvent.ParticipantDisconnected, refresh);
      room.off(RoomEvent.ActiveSpeakersChanged, refresh);
    };
  }, [room]);

  const present = Boolean(agent) || remoteCount > 0;
  if (!present) return "joining";
  if (voiceAssistantState === "speaking" || remoteSpeaking) return "speaking";
  if (voiceAssistantState === "thinking") return "thinking";
  if (voiceAssistantState === "listening") return "listening";
  return "starting";
}

function interviewerStatusCopy(
  agentName: string,
  waitingLabel: string,
  state: string,
): { title: string; detail: string } {
  switch (state) {
    case "speaking":
      return { title: agentName, detail: "Talking" };
    case "thinking":
      return { title: agentName, detail: "Preparing the next question" };
    case "listening":
      return { title: agentName, detail: "Listening" };
    case "starting":
      return { title: agentName, detail: "Starting the interview" };
    case "joining":
      return {
        title: agentName,
        detail: waitingLabel || "The interviewer is joining…",
      };
    default:
      return { title: agentName, detail: "Starting the interview" };
  }
}

function connectionCopy(connectionState: string) {
  if (connectionState === "connected") return "live";
  if (connectionState === "connecting") return "joining";
  return connectionState;
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
  const { state } = useVoiceAssistant();
  const liveState = useInterviewerLiveState(state);
  const copy = interviewerStatusCopy(agentName, waitingLabel, liveState);

  return (
    <section
      className="agent-presence agent-panel"
      data-voice-ui="agent-status"
      data-agent-state={liveState}
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
        <span className="agent-kicker">AI interviewer</span>
        <strong>{copy.title}</strong>
        <p>{copy.detail}</p>
      </div>
      <p className="video-label">{participantLabel}</p>
    </section>
  );
}

export function VoiceSessionControls({
  cameraAllowed = true,
  confirmEnd = true,
}: {
  cameraAllowed?: boolean;
  confirmEnd?: boolean;
}) {
  const [confirming, setConfirming] = useState(false);
  const continueButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (confirming) continueButton.current?.focus();
  }, [confirming]);

  return (
    <>
      <div
        className="session-controls"
        aria-label="Interview controls"
        data-voice-ui="controls"
      >
        <div className="lk-button-group">
          <TrackToggle source={Track.Source.Microphone}>
            <span>Microphone</span>
          </TrackToggle>
          <div className="lk-button-group-menu">
            <MediaDeviceMenu kind="audioinput" />
          </div>
        </div>
        {cameraAllowed ? (
          <TrackToggle source={Track.Source.Camera}>
            <span>Camera</span>
          </TrackToggle>
        ) : null}
        {confirmEnd ? (
          <button
            className="lk-button lk-disconnect-button"
            type="button"
            onClick={() => setConfirming(true)}
          >
            End interview
          </button>
        ) : (
          <DisconnectButton>
            <span>End interview</span>
          </DisconnectButton>
        )}
      </div>
      {confirming ? (
        <div className="end-confirmation" role="dialog" aria-modal="true"
          aria-labelledby="end-confirmation-title"
          onKeyDown={(event) => {
            if (event.key === "Escape") setConfirming(false);
          }}>
          <div>
            <strong id="end-confirmation-title">End this interview?</strong>
            <p>You will leave the room and cannot continue this attempt.</p>
            <div className="button-row">
              <button ref={continueButton} className="button secondary" type="button"
                onClick={() => setConfirming(false)}>
                Continue interview
              </button>
              <DisconnectButton>
                <span>End interview</span>
              </DisconnectButton>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

export function DefaultVoiceSession({
  labels,
}: {
  labels: VoiceSessionLabels;
}) {
  const connectionState = useConnectionState();
  const { state: agentState } = useVoiceAssistant();
  const liveState = useInterviewerLiveState(agentState);
  const agentCopy = interviewerStatusCopy(
    labels.agentName,
    labels.waitingForAgent || "The interviewer is joining…",
    liveState,
  );

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
            Connection <strong>{connectionCopy(connectionState)}</strong>
          </span>
          <span className="status-pill agent-state-pill">
            Interviewer <strong>{agentCopy.detail}</strong>
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
        <VoiceSessionControls cameraAllowed={labels.cameraAllowed} />
      </footer>
    </div>
  );
}

export type VoiceTranscriptLine = {
  id: string;
  who: "candidate" | "agent";
  text: string;
  final: boolean;
};

export function useVoiceTranscriptLines(limit = 40): VoiceTranscriptLine[] {
  const streams = useTranscriptions();
  const { agentTranscriptions } = useVoiceAssistant();
  const [lines, setLines] = useState<VoiceTranscriptLine[]>([]);

  useEffect(() => {
    const incoming: VoiceTranscriptLine[] = [
      ...streams.map((item) => ({
        id: item.streamInfo.id,
        who: "candidate" as const,
        text: item.text.trim(),
        final: true,
      })),
      ...agentTranscriptions.map((segment) => ({
        id: segment.id,
        who: "agent" as const,
        text: segment.text.trim(),
        final: segment.final,
      })),
    ].filter((line) => line.text);
    if (incoming.length === 0) return;
    setLines((current) => {
      const next = [...current];
      let changed = false;
      for (const line of incoming) {
        const key = `${line.who}:${line.id}`;
        const index = next.findIndex(
          (existing) => `${existing.who}:${existing.id}` === key,
        );
        if (index >= 0) {
          const existing = next[index];
          if (existing.text !== line.text || existing.final !== line.final) {
            next[index] = line;
            changed = true;
          }
        } else {
          next.push(line);
          changed = true;
        }
      }
      if (!changed) return current;
      return next.slice(-limit);
    });
  }, [agentTranscriptions, limit, streams]);

  return lines;
}

export function VoiceTranscripts({
  candidateLabel = "You",
  agentLabel = "AI Interviewer",
  maxLines = 40,
}: {
  candidateLabel?: string;
  agentLabel?: string;
  maxLines?: number;
}) {
  const lines = useVoiceTranscriptLines(maxLines);
  const latestFinal = [...lines].reverse().find((line) => line.final);

  return (
    <section className="transcript-panel" data-voice-ui="transcripts"
      aria-label="Live interview transcript">
      <div className="transcript-heading">
        <div>
          <p className="step-label">Live transcript</p>
          <h3>Conversation</h3>
        </div>
        <span className="transcript-status">Live</span>
      </div>
      {lines.length === 0 ? (
        <p className="transcript-empty">
          The conversation will appear here when the interview begins.
        </p>
      ) : (
        <ol className="transcript-list">
          {lines.map((line) => (
            <li key={`${line.who}:${line.id}`} data-final={line.final}>
              <span>{line.who === "agent" ? agentLabel : candidateLabel}</span>
              <p>{line.text}</p>
              {!line.final ? <small>Speaking…</small> : null}
            </li>
          ))}
        </ol>
      )}
      <p className="sr-only" aria-live="polite" aria-atomic="true">
        {latestFinal
          ? `${latestFinal.who === "agent" ? agentLabel : candidateLabel}: ${latestFinal.text}`
          : ""}
      </p>
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
