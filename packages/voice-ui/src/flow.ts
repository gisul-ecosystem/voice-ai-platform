export type VoiceFlowStage =
  | "setup"
  | "prejoin"
  | "connecting"
  | "live"
  | "completed";

export type VoiceFlowEvent =
  | "setup-submitted"
  | "devices-confirmed"
  | "connected"
  | "disconnected"
  | "restart";

const transitions: Record<
  VoiceFlowStage,
  Partial<Record<VoiceFlowEvent, VoiceFlowStage>>
> = {
  setup: { "setup-submitted": "prejoin" },
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
