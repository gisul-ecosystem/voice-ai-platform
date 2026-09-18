"use client";

import {
  RoomAudioRenderer,
  useConnectionState,
} from "@livekit/components-react";
import {
  VoiceAgentStatus,
  VoiceSessionControls,
  VoiceTranscripts,
} from "@gisul/voice-ui";
import { useEffect, useState } from "react";

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

      <div className="interview-workspace">
        <section className="interviewer-stage" aria-label="AI interviewer">
          <VoiceAgentStatus
            agentName="AI Interviewer"
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
            </div>
          </div>
        </section>
        <VoiceTranscripts
          candidateLabel="You"
          agentLabel="AI Interviewer"
          maxLines={60}
        />
      </div>

      <RoomAudioRenderer />
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
