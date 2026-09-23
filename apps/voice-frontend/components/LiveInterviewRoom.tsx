"use client";

import {
  VoiceRoom,
  type VoiceSessionCredentials,
} from "@gisul/voice-ui";

import { CandidateLiveInterview } from "@/components/CandidateLiveInterview";
import type { DeviceChoices } from "@/components/DevicePreJoin";

export function LiveInterviewRoom({
  credentials,
  choices,
  title,
  candidateName,
  cameraAllowed,
  onConnected,
  onDisconnected,
  onError,
  onEndRequested,
}: {
  credentials: VoiceSessionCredentials;
  choices: DeviceChoices;
  title: string;
  candidateName: string;
  cameraAllowed: boolean;
  onConnected: () => void;
  onDisconnected: () => void;
  onError: (error: Error) => void;
  onEndRequested: () => void;
}) {
  return (
    <VoiceRoom
      credentials={credentials}
      choices={choices}
      className="candidate-live-room"
      onConnected={onConnected}
      onDisconnected={onDisconnected}
      onError={onError}
    >
      <CandidateLiveInterview
        title={title}
        candidateName={candidateName}
        cameraAllowed={cameraAllowed}
        onEndRequested={onEndRequested}
      />
    </VoiceRoom>
  );
}
