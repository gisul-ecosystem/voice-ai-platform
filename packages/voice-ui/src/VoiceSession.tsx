"use client";

import {
  DisconnectButton,
  LiveKitRoom,
  MediaDeviceMenu,
  RoomAudioRenderer,
  StartAudio,
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
        choices.audioEnabled
          ? {
              deviceId: choices.audioDeviceId,
              echoCancellation: true,
              noiseSuppression: true,
              autoGainControl: true,
            }
          : false
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
  onEndRequested,
}: {
  cameraAllowed?: boolean;
  confirmEnd?: boolean;
  onEndRequested?: () => void;
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
          <DisconnectButton onClick={onEndRequested}>
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
              <DisconnectButton onClick={onEndRequested}>
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
      <StartAudio
        className="button primary start-audio-button"
        label="Click to enable interviewer audio"
      />
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
  /** Epoch ms when the segment was first seen; used for stable chronological order. */
  at?: number;
};

export function normalizeTranscriptText(text: string): string {
  return text.trim().replace(/\s+/g, " ").toLowerCase();
}

function wordOverlapRatio(a: string, b: string): number {
  const aWords = new Set(a.split(" ").filter((w) => w.length > 1));
  const bWords = new Set(b.split(" ").filter((w) => w.length > 1));
  if (aWords.size === 0 || bWords.size === 0) return 0;
  let shared = 0;
  for (const word of aWords) if (bWords.has(word)) shared += 1;
  return shared / Math.min(aWords.size, bWords.size);
}

export function isLikelyAgentIdentity(
  identity: string,
  agentIdentity = "",
): boolean {
  const value = identity.trim().toLowerCase();
  if (!value) return false;
  const agent = agentIdentity.trim().toLowerCase();
  if (agent && value === agent) return true;
  return (
    value.includes("agent") ||
    value.startsWith("aaptor") ||
    value.includes("interviewer")
  );
}

/** Drop speaker-echo / duplicated agent text wrongly labeled as the candidate. */
export function isEchoOfAgentSpeech(
  candidateText: string,
  agentTexts: string[],
): boolean {
  const cand = normalizeTranscriptText(candidateText);
  if (cand.length < 12) return false;
  const candTokens = new Set(cand.split(" ").filter((token) => token.length > 2));
  for (const raw of agentTexts) {
    const agent = normalizeTranscriptText(raw);
    if (!agent || agent.length < 12) continue;
    if (cand === agent) return true;
    if (agent.includes(cand) && cand.length >= 18) return true;
    if (cand.includes(agent) && agent.length >= 18) return true;
    const agentTokens = agent.split(" ").filter((token) => token.length > 2);
    if (agentTokens.length < 3 || candTokens.size < 3) continue;
    let overlap = 0;
    for (const token of agentTokens) {
      if (candTokens.has(token)) overlap += 1;
    }
    const ratio = overlap / Math.min(agentTokens.length, candTokens.size);
    if (ratio >= 0.55 && Math.min(cand.length, agent.length) >= 24) return true;
  }
  return false;
}

/** True for short/looping STT fragments that usually come from speaker echo. */
export function isLikelyEchoFragment(text: string): boolean {
  const words = normalizeTranscriptText(text)
    .split(" ")
    .filter(Boolean);
  if (words.length === 0) return true;
  if (words.length <= 5) return true;
  if (words.length >= 6 && new Set(words).size <= 3) return true;
  // Repeated starter phrases from bad STT on TTS playback.
  const joined = words.join(" ");
  if (/^(there are (the |many )?)+/.test(joined) && words.length <= 12) {
    return true;
  }
  return false;
}

/** Merge growing/corrected STT fragments into one line per underlying segment. */
export function coalesceTranscriptLines(
  lines: VoiceTranscriptLine[],
): VoiceTranscriptLine[] {
  const chronological = [...lines]
    .filter((line) => line.text.trim())
    .sort((a, b) => (a.at ?? 0) - (b.at ?? 0));

  const result: VoiceTranscriptLine[] = [];
  const indexById = new Map<string, number>();
  for (const line of chronological) {
    if (!line.text) continue;
    const existingIndex = indexById.get(line.id);
    if (existingIndex !== undefined) {
      // Same underlying STT segment revised (e.g. interim guess -> corrected
      // final text) — replace in place rather than opening a new box.
      result[existingIndex] = line;
      continue;
    }
    const last = result[result.length - 1];
    if (last && last.who === line.who) {
      const prev = normalizeTranscriptText(last.text);
      const next = normalizeTranscriptText(line.text);
      const shortGap =
        last.at !== undefined &&
        line.at !== undefined &&
        line.at >= last.at &&
        line.at - last.at <= 1800;
      const unfinishedCandidateFragment =
        line.who === "candidate" &&
        shortGap &&
        !/[.!?]$/.test(last.text.trim()) &&
        (last.text.trim().split(/\s+/).length <= 10 ||
          line.text.trim().split(/\s+/).length <= 10) &&
        !next.startsWith(prev) &&
        !prev.startsWith(next) &&
        !next.includes(prev) &&
        !prev.includes(next) &&
        wordOverlapRatio(prev, next) < 0.7;
      if (
        next === prev ||
        next.startsWith(prev) ||
        prev.startsWith(next) ||
        next.includes(prev) ||
        // Late-arriving corrected transcript on a new stream id, but clearly
        // the same spoken utterance (e.g. STT rewrote wording after commit).
        wordOverlapRatio(prev, next) >= 0.7 ||
        unfinishedCandidateFragment
      ) {
        const mergedIndex = result.length - 1;
        result[mergedIndex] = {
          ...line,
          id: last.id,
          text: unfinishedCandidateFragment
            ? `${last.text.trim()} ${line.text.trim()}`
            : line.text.length >= last.text.length
              ? line.text
              : last.text,
          final: last.final || line.final,
        };
        indexById.set(last.id, mergedIndex);
        continue;
      }
    }
    indexById.set(line.id, result.length);
    result.push(line);
  }

  // Second pass: remove candidate lines that are echoes of nearby agent speech.
  const agentTexts = result
    .filter((line) => line.who === "agent")
    .map((line) => line.text);
  return result.filter((line) => {
    if (line.who !== "candidate") return true;
    if (isEchoOfAgentSpeech(line.text, agentTexts)) return false;
    return true;
  });
}

export function useVoiceTranscriptLines(limit = 40): VoiceTranscriptLine[] {
  const streams = useTranscriptions();
  const { agent, agentTranscriptions, state: agentState } = useVoiceAssistant();
  const agentIdentity = agent?.identity?.trim() || "";
  const agentBusy =
    agentState === "speaking" || agentState === "thinking";

  const fromAgent: VoiceTranscriptLine[] = agentTranscriptions.map((segment) => ({
    id: `agent:${segment.id}`,
    who: "agent" as const,
    text: segment.text.trim(),
    final: Boolean(segment.final),
    at: Number(segment.firstReceivedTime || segment.lastReceivedTime || 0) || undefined,
  }));

  const agentTexts = fromAgent.map((line) => line.text).filter(Boolean);

  const fromStreams: VoiceTranscriptLine[] = [];
  for (const item of streams) {
    const text = item.text.trim();
    if (!text) continue;
    const identity = String(item.participantInfo?.identity || "").trim();
    const agentLine = isLikelyAgentIdentity(identity, agentIdentity);
    const at = Number(item.streamInfo.timestamp || 0) || undefined;

    if (agentLine) {
      // Prefer useVoiceAssistant segments; only keep stream agent text if new.
      if (
        isEchoOfAgentSpeech(text, agentTexts) ||
        agentTexts.some(
          (agentText) =>
            normalizeTranscriptText(agentText) === normalizeTranscriptText(text),
        )
      ) {
        continue;
      }
      fromStreams.push({
        id: `stream-agent:${item.streamInfo.id}`,
        who: "agent",
        text,
        final: true,
        at,
      });
      continue;
    }

    // Empty identity while the agent is talking is almost always TTS echo / text stream bleed.
    if (!identity && agentBusy) {
      if (!isLikelyEchoFragment(text) && text.split(/\s+/).length >= 10) {
        fromStreams.push({
          id: `stream-agent-unknown:${item.streamInfo.id}`,
          who: "agent",
          text,
          final: true,
          at,
        });
      }
      continue;
    }

    if (agentBusy && isLikelyEchoFragment(text)) continue;
    if (isEchoOfAgentSpeech(text, agentTexts)) continue;

    fromStreams.push({
      id: `stream:${item.streamInfo.id}`,
      who: "candidate",
      text,
      final: true,
      at,
    });
  }

  const incoming = [...fromAgent, ...fromStreams];
  return coalesceTranscriptLines(incoming).slice(-limit);
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
  const listRef = useRef<HTMLOListElement | null>(null);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    list.scrollTop = list.scrollHeight;
  }, [lines]);

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
        <ol className="transcript-list" ref={listRef}>
          {lines.map((line) => (
            <li key={line.id} data-final={line.final} data-who={line.who}>
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
