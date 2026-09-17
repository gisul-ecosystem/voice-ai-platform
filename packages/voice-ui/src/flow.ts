export type VoiceFlowStage =
  | "setup"
  | "preview"
  | "prejoin"
  | "connecting"
  | "live"
  | "completed";

export type VoiceFlowEvent =
  | "setup-submitted"
  | "preview-confirmed"
  | "devices-confirmed"
  | "connected"
  | "disconnected"
  | "restart";

const transitions: Record<
  VoiceFlowStage,
  Partial<Record<VoiceFlowEvent, VoiceFlowStage>>
> = {
  setup: { "setup-submitted": "preview" },
  preview: { "preview-confirmed": "prejoin", restart: "setup" },
  prejoin: { "devices-confirmed": "connecting", restart: "setup" },
  connecting: {
    connected: "live",
    disconnected: "completed",
    restart: "setup",
  },
  live: { disconnected: "completed" },
  completed: { restart: "setup" },
};

export function transitionVoiceFlow(
  stage: VoiceFlowStage,
  event: VoiceFlowEvent,
): VoiceFlowStage {
  return transitions[stage][event] ?? stage;
}
