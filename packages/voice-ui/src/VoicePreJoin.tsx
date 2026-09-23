"use client";

import {
  MediaDeviceMenu,
  TrackToggle,
  usePersistentUserChoices,
  usePreviewTracks,
} from "@livekit/components-react";
import {
  LocalAudioTrack,
  LocalVideoTrack,
  Track,
} from "livekit-client";
import { useEffect, useMemo, useRef, useState } from "react";

import type { VoiceDeviceChoices } from "./types";

export type VoicePreJoinProps = {
  participantName: string;
  cameraAllowed?: boolean;
  cameraEnabledByDefault?: boolean;
  joinLabel?: string;
  persistUserChoices?: boolean;
  allowNameEditing?: boolean;
  className?: string;
  onSubmit: (choices: VoiceDeviceChoices) => void;
  onError?: (error: Error) => void;
};

export function VoicePreJoin({
  participantName,
  cameraAllowed = true,
  cameraEnabledByDefault = false,
  joinLabel = "Join session",
  persistUserChoices = true,
  allowNameEditing = true,
  className,
  onSubmit,
  onError,
}: VoicePreJoinProps) {
  const {
    userChoices: initialChoices,
    saveAudioInputDeviceId,
    saveAudioInputEnabled,
    saveVideoInputDeviceId,
    saveVideoInputEnabled,
    saveUsername,
  } = usePersistentUserChoices({
    defaults: {
      username: participantName,
      audioEnabled: true,
      videoEnabled: cameraAllowed && cameraEnabledByDefault,
    },
    preventSave: !persistUserChoices,
    preventLoad: !persistUserChoices,
  });
  const [username, setUsername] = useState(
    allowNameEditing
      ? initialChoices.username || participantName
      : participantName,
  );
  const [audioEnabled, setAudioEnabled] = useState(
    initialChoices.audioEnabled,
  );
  const [videoEnabled, setVideoEnabled] = useState(
    cameraAllowed && cameraEnabledByDefault && initialChoices.videoEnabled,
  );
  const [audioDeviceId, setAudioDeviceId] = useState(
    initialChoices.audioDeviceId,
  );
  const [videoDeviceId, setVideoDeviceId] = useState(
    initialChoices.videoDeviceId,
  );
  const tracks = usePreviewTracks(
    {
      audio: audioEnabled ? { deviceId: audioDeviceId } : false,
      video: cameraAllowed && videoEnabled ? { deviceId: videoDeviceId } : false,
    },
    onError,
  );
  const videoTrack = useMemo(
    () =>
      tracks?.find((track) => track.kind === Track.Kind.Video) as
        | LocalVideoTrack
        | undefined,
    [tracks],
  );
  const audioTrack = useMemo(
    () =>
      tracks?.find((track) => track.kind === Track.Kind.Audio) as
        | LocalAudioTrack
        | undefined,
    [tracks],
  );
  const videoElement = useRef<HTMLVideoElement>(null);

  useEffect(() => {
    if (videoElement.current && videoTrack) {
      void videoTrack.unmute();
      videoTrack.attach(videoElement.current);
    }
    return () => {
      videoTrack?.detach();
    };
  }, [videoTrack]);

  useEffect(() => {
    if (allowNameEditing) saveUsername(username);
  }, [allowNameEditing, saveUsername, username]);
  useEffect(() => {
    saveAudioInputEnabled(audioEnabled);
  }, [audioEnabled, saveAudioInputEnabled]);
  useEffect(() => {
    saveVideoInputEnabled(videoEnabled);
  }, [saveVideoInputEnabled, videoEnabled]);
  useEffect(() => {
    saveAudioInputDeviceId(audioDeviceId);
  }, [audioDeviceId, saveAudioInputDeviceId]);
  useEffect(() => {
    saveVideoInputDeviceId(videoDeviceId);
  }, [saveVideoInputDeviceId, videoDeviceId]);

  function join() {
    const normalizedName = username.trim();
    if (!normalizedName || !audioEnabled || !audioTrack) return;
    onSubmit({
      username: normalizedName,
      audioEnabled,
      videoEnabled: cameraAllowed && videoEnabled,
      audioDeviceId,
      videoDeviceId,
    });
  }

  return (
    <div
      className={["voice-device-check", className].filter(Boolean).join(" ")}
    >
      {cameraAllowed ? (
        <div className="voice-device-preview">
          {videoEnabled && videoTrack ? (
            <video ref={videoElement} autoPlay muted playsInline />
          ) : (
            <div className="voice-device-placeholder">
              <span>Camera preview is off</span>
            </div>
          )}
          <span className="voice-preview-label">Preview</span>
        </div>
      ) : (
        <div className="voice-audio-preview" aria-live="polite">
          <div className="audio-preview-mark" aria-hidden="true">
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
          <strong>
            {!audioEnabled
              ? "Microphone is muted"
              : audioTrack
                ? "Microphone is ready"
                : "Waiting for microphone permission"}
          </strong>
          <p>Speak naturally and confirm that your browser shows microphone access.</p>
        </div>
      )}

      <div className="voice-device-settings">
        <label className="voice-device-name">
          <span>Display name</span>
          <input
            className="lk-form-control"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            autoComplete="name"
            required
            readOnly={!allowNameEditing}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                join();
              }
            }}
          />
        </label>

        <div className="voice-device-row">
          <div>
            <strong>Microphone</strong>
            <span>{audioEnabled ? "Ready" : "Muted"}</span>
          </div>
          <div className="lk-button-group">
            <TrackToggle
              initialState={audioEnabled}
              source={Track.Source.Microphone}
              onChange={setAudioEnabled}
            >
              {audioEnabled ? "On" : "Off"}
            </TrackToggle>
            <div className="lk-button-group-menu">
              <MediaDeviceMenu
                initialSelection={audioDeviceId}
                kind="audioinput"
                disabled={!audioTrack}
                tracks={{ audioinput: audioTrack }}
                onActiveDeviceChange={(_, id) => setAudioDeviceId(id)}
              />
            </div>
          </div>
        </div>

        {cameraAllowed ? (
          <div className="voice-device-row">
            <div>
              <strong>Camera</strong>
              <span>{videoEnabled ? "Ready" : "Off"}</span>
            </div>
            <div className="lk-button-group">
              <TrackToggle
                initialState={videoEnabled}
                source={Track.Source.Camera}
                onChange={setVideoEnabled}
              >
                {videoEnabled ? "On" : "Off"}
              </TrackToggle>
              <div className="lk-button-group-menu">
                <MediaDeviceMenu
                  initialSelection={videoDeviceId}
                  kind="videoinput"
                  disabled={!videoTrack}
                  tracks={{ videoinput: videoTrack }}
                  onActiveDeviceChange={(_, id) => setVideoDeviceId(id)}
                />
              </div>
            </div>
          </div>
        ) : null}

        <button
          className="lk-button voice-join-button"
          type="button"
          disabled={!username.trim() || !audioEnabled || !audioTrack}
          onClick={join}
        >
          {joinLabel}
        </button>
      </div>
    </div>
  );
}
