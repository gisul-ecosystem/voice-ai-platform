"use client";

import {
  RoomAudioRenderer,
  StartAudio,
  useConnectionState,
} from "@livekit/components-react";
import {
  VoiceAgentStatus,
  VoiceSessionControls,
  VoiceTranscripts,
  useVoiceTranscriptLines,
} from "@gisul/voice-ui";
import { useEffect, useRef, useState } from "react";

// ---------------------------------------------------------------------------
// Guardrail config — read from NEXT_PUBLIC_ env at build time.
// Default ON when env var is absent or set to any value other than "false"/"0".
// ---------------------------------------------------------------------------
function _flag(name: string, def = true): boolean {
  const val = (process.env[name] ?? "").trim().toLowerCase();
  if (!val) return def;
  return val !== "0" && val !== "false" && val !== "off" && val !== "no";
}

const GUARDRAIL_CAPTIONS: boolean = _flag(
  "NEXT_PUBLIC_GUARDRAIL_CAPTIONS",
);
const GUARDRAIL_SPEED_CONTROL: boolean = _flag(
  "NEXT_PUBLIC_GUARDRAIL_SPEED_CONTROL",
);

// ---------------------------------------------------------------------------
// Live caption banner — shows the latest agent question as ARIA-assertive text
// ---------------------------------------------------------------------------
function LiveCaptionBanner({
  agentLabel,
}: {
  agentLabel: string;
}) {
  const lines = useVoiceTranscriptLines(10);
  // Show the latest agent (interviewer) line that is final.
  const latestAgentLine = [...lines]
    .reverse()
    .find((line) => line.who === "agent" && line.final);

  const [displayed, setDisplayed] = useState<string>("");
  const prevId = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!latestAgentLine) return;
    if (latestAgentLine.id === prevId.current) return;
    prevId.current = latestAgentLine.id;
    setDisplayed(latestAgentLine.text);
  }, [latestAgentLine]);

  if (!displayed) return null;

  return (
    <div
      className="caption-banner"
      aria-live="assertive"
      aria-atomic="true"
      role="status"
    >
      <span className="caption-label">{agentLabel}</span>
      <p className="caption-text">{displayed}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Speech speed control — adjusts a CSS custom property used by TTS playback
// rate. The `<audio>` element exposed by LiveKit's RoomAudioRenderer is in
// Shadow DOM; we apply the rate to all <audio> elements on the page instead.
// ---------------------------------------------------------------------------
function SpeedControl({
  speedRate,
  onChange,
}: {
  speedRate: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="speed-control" aria-label="Interviewer speech speed">
      <label htmlFor="speech-speed-range" className="speed-control-label">
        Speed: {speedRate.toFixed(1)}×
      </label>
      <input
        id="speech-speed-range"
        type="range"
        min={0.5}
        max={2.0}
        step={0.1}
        value={speedRate}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        aria-valuemin={0.5}
        aria-valuemax={2.0}
        aria-valuenow={speedRate}
        aria-valuetext={`${speedRate.toFixed(1)} times normal speed`}
      />
    </div>
  );
}

/** Apply playback rate to every <audio> element on the page. */
function useAudioPlaybackRate(rate: number) {
  useEffect(() => {
    const audios = document.querySelectorAll<HTMLAudioElement>("audio");
    audios.forEach((audio) => {
      try {
        audio.playbackRate = rate;
      } catch {
        // Ignore — some browsers throw if the element is not yet playing.
      }
    });
  }, [rate]);
}

export function CandidateLiveInterview({
  title,
  candidateName,
  cameraAllowed,
  onEndRequested,
}: {
  title: string;
  candidateName: string;
  cameraAllowed: boolean;
  onEndRequested: () => void;
}) {
  const connectionState = useConnectionState();
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [speedRate, setSpeedRate] = useState(1.0);

  useAudioPlaybackRate(speedRate);

  useEffect(() => {
    const timer = window.setInterval(
      () => setElapsedSeconds((current) => current + 1),
      1_000,
    );
    return () => window.clearInterval(timer);
  }, []);

  const minutes = Math.floor(elapsedSeconds / 60)
    .toString()
    .padStart(2, "0");
  const seconds = (elapsedSeconds % 60).toString().padStart(2, "0");
  const connectionLabel =
    connectionState === "connected" ? "Connected" : "Reconnecting";

  return (
    <div
      className="interview-room"
      data-connection={connectionState}
      data-candidate-stage="live"
    >
      <header className="interview-room-header">
        <div>
          <p className="session-live-label">
            <span className="live-dot" aria-hidden="true" />
            Interview in progress
          </p>
          <h2 tabIndex={-1}>{title}</h2>
        </div>
        <div className="interview-meta" aria-live="polite">
          <span>
            {minutes}:{seconds}
          </span>
          <span className="connection-label">{connectionLabel}</span>
        </div>
      </header>

      {connectionState !== "connected" ? (
        <div className="connection-banner" role="status">
          Connection interrupted. Keep this page open while we reconnect.
        </div>
      ) : null}

      {/* Guardrail: live caption banner for latest interviewer question */}
      {GUARDRAIL_CAPTIONS ? (
        <LiveCaptionBanner agentLabel="Interviewer" />
      ) : null}

      <div className="interview-workspace">
        <section className="interviewer-stage" aria-label="AI interviewer">
          <VoiceAgentStatus
            agentName="Interviewer"
            participantLabel="Structured voice interview"
            waitingLabel="The interviewer is joining the room"
          />
          <div className="candidate-speaking-note">
            <span className="candidate-initial" aria-hidden="true">
              {(candidateName || "?").slice(0, 1).toUpperCase()}
            </span>
            <div>
              <strong>{candidateName}</strong>
              <p>Answer naturally. You can pause to think before continuing.</p>
              <p className="repeat-hint">
                Say <em>"repeat that"</em> to hear the question again.
              </p>
            </div>
          </div>

          {/* Guardrail: speech speed control */}
          {GUARDRAIL_SPEED_CONTROL ? (
            <SpeedControl speedRate={speedRate} onChange={setSpeedRate} />
          ) : null}
        </section>
        <VoiceTranscripts
          candidateLabel="Candidate"
          agentLabel="Interviewer"
          maxLines={60}
        />
      </div>

      <RoomAudioRenderer />
      <StartAudio
        className="button primary interview-start-audio"
        label="Enable interviewer audio"
      />
      <footer className="interview-control-dock">
        <p>Your microphone audio is sent through the secure interview room.</p>
        <VoiceSessionControls
          cameraAllowed={cameraAllowed}
          onEndRequested={onEndRequested}
        />
      </footer>
    </div>
  );
}
