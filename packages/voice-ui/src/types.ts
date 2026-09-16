import type { PreJoinProps } from "@livekit/components-react";

export type VoiceDeviceChoices = Parameters<
  NonNullable<PreJoinProps["onSubmit"]>
>[0];

export type VoiceSessionCredentials = {
  room: string;
  token: string;
  livekitUrl: string;
  productId: string;
};

export type VoiceSessionLabels = {
  title: string;
  agentName: string;
  localParticipant?: string;
  agentParticipant?: string;
  waitingForAgent?: string;
};

export type VoiceSessionRequest = {
  productId: string;
  participantName: string;
  jobDescription?: string;
  resumeText?: string;
};
