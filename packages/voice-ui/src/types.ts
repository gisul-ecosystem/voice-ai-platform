import type { PreJoinProps } from "@livekit/components-react";

export type VoiceDeviceChoices = Parameters<
  NonNullable<PreJoinProps["onSubmit"]>
>[0];

export type VoiceSessionCredentials = {
  room: string;
  token: string;
  livekitUrl: string;
  productId: string;
  sessionId?: string;
};

export type VoiceSessionLabels = {
  title: string;
  agentName: string;
  localParticipant?: string;
  agentParticipant?: string;
  waitingForAgent?: string;
  cameraAllowed?: boolean;
};

export type VoiceSessionRequest = {
  productId: string;
  participantName: string;
  jobDescription?: string;
  resumeText?: string;
  invitationToken?: string;
  idempotencyKey?: string;
  interviewSetup?: {
    title: string;
    role: string;
    seniority: string;
    difficulty: string;
    durationMinutes: number;
    language: string;
    competencies: string[];
    maxProbesPerPhase: number;
    monitoringEnabled: boolean;
    recordingEnabled: boolean;
  };
};
