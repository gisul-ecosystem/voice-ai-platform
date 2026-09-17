"use client";

import {
  VoicePreJoin,
  type VoiceDeviceChoices,
} from "@gisul/voice-ui";

import type { ProductConfig } from "@/lib/products";

export type DeviceChoices = VoiceDeviceChoices;

type DevicePreJoinProps = {
  product: ProductConfig;
  participantName: string;
  onBack: () => void;
  onSubmit: (choices: DeviceChoices) => void;
  onError: (error: Error) => void;
};

export function DevicePreJoin({
  product,
  participantName,
  onBack,
  onSubmit,
  onError,
}: DevicePreJoinProps) {
  return (
    <div className="prejoin-shell" data-lk-theme="default">
      <div className="section-heading">
        <p className="step-label">Device check</p>
        <h2>
          Confirm microphone{product.cameraAllowed ? " and camera" : ""} access
        </h2>
        <p>
          {product.cameraAllowed
            ? "Choose your devices, verify the preview, then confirm that you are ready to join."
            : "Camera is disabled for this environment. Confirm your microphone before joining."}
        </p>
      </div>
      <VoicePreJoin
        participantName={participantName}
        cameraAllowed={product.cameraAllowed}
        cameraEnabledByDefault={product.cameraEnabledByDefault}
        joinLabel={`I am ready — ${product.joinLabel}`}
        onSubmit={onSubmit}
        onError={onError}
      />
      <button className="button secondary" type="button" onClick={onBack}>
        Back to setup
      </button>
    </div>
  );
}
