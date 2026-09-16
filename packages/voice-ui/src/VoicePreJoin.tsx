"use client";

import { PreJoin } from "@livekit/components-react";

import type { VoiceDeviceChoices } from "./types";

export type VoicePreJoinProps = {
  participantName: string;
  cameraEnabledByDefault?: boolean;
  joinLabel?: string;
  persistUserChoices?: boolean;
  className?: string;
  onSubmit: (choices: VoiceDeviceChoices) => void;
  onError?: (error: Error) => void;
};

export function VoicePreJoin({
  participantName,
  cameraEnabledByDefault = false,
  joinLabel = "Join session",
  persistUserChoices = true,
  className,
  onSubmit,
  onError,
}: VoicePreJoinProps) {
  return (
    <PreJoin
      className={className}
      defaults={{
        username: participantName,
        audioEnabled: true,
        videoEnabled: cameraEnabledByDefault,
      }}
      persistUserChoices={persistUserChoices}
      joinLabel={joinLabel}
      onSubmit={onSubmit}
      onError={onError}
    />
  );
}
