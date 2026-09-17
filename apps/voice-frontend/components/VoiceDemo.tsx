"use client";

import {
  VoiceSession,
  createVoiceSession,
  transitionVoiceFlow,
  type VoiceFlowStage,
  type VoiceSessionCredentials,
} from "@gisul/voice-ui";
import Link from "next/link";
import { useState } from "react";

import {
  DevicePreJoin,
  type DeviceChoices,
} from "@/components/DevicePreJoin";
import { CandidatePreview } from "@/components/CandidatePreview";
import { SetupForm } from "@/components/SetupForm";
import type { ProductConfig } from "@/lib/products";
import type { PublicSessionRequest } from "@/lib/session-contract";

export function VoiceDemo({ product }: { product: ProductConfig }) {
  const [stage, setStage] = useState<VoiceFlowStage>("setup");
  const [setup, setSetup] = useState<PublicSessionRequest>();
  const [choices, setChoices] = useState<DeviceChoices>();
  const [credentials, setCredentials] = useState<VoiceSessionCredentials>();
  const [error, setError] = useState<string>();

  function continueFromSetup(value: PublicSessionRequest) {
    setSetup(value);
    setError(undefined);
    setStage(
      product.id === "interviewer"
        ? (current) => transitionVoiceFlow(current, "setup-submitted")
        : "prejoin",
    );
  }

  async function join(values: DeviceChoices) {
    if (!setup) return;
    const request = {
      ...setup,
      participantName: values.username.trim() || setup.participantName,
    };
    setSetup(request);
    setChoices(values);
    setError(undefined);
    setStage("connecting");
    try {
      setCredentials(await createVoiceSession(request));
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "The session could not be created.",
      );
      setStage("prejoin");
    }
  }

  function restart() {
    setCredentials(undefined);
    setChoices(undefined);
    setError(undefined);
    setStage((current) => transitionVoiceFlow(current, "restart"));
  }

  function finish(reason?: Error) {
    if (reason) setError(reason.message || "The voice connection ended.");
    setCredentials(undefined);
    setStage("completed");
  }

  return (
    <main className={`demo-page demo-stage-${stage}`}>
      <nav className="topbar" aria-label="Demo navigation">
        <Link href="/" className="brand">
          Voice AI Platform
        </Link>
        <span>{product.eyebrow}</span>
      </nav>

      <section className="demo-intro">
        <p className="eyebrow">{product.eyebrow}</p>
        <h1>{product.title}</h1>
        <p>{product.description}</p>
      </section>

      <section className="demo-card">
        {error ? (
          <div className="alert" role="alert">
            {error}
          </div>
        ) : null}

        {stage === "setup" ? (
          <SetupForm
            product={product}
            initialValue={setup}
            onContinue={continueFromSetup}
          />
        ) : null}

        {stage === "preview" && setup ? (
          <CandidatePreview
            request={setup}
            onBack={() => setStage("setup")}
            onContinue={() =>
              setStage((current) =>
                transitionVoiceFlow(current, "preview-confirmed"),
              )
            }
          />
        ) : null}

        {stage === "prejoin" && setup ? (
          <DevicePreJoin
            product={product}
            participantName={setup.participantName}
            onBack={() =>
              setStage(product.id === "interviewer" ? "preview" : "setup")
            }
            onSubmit={join}
            onError={(reason) => setError(reason.message)}
          />
        ) : null}

        {stage === "connecting" && !credentials ? (
          <div className="center-state" role="status">
            <span className="spinner" aria-hidden="true" />
            <h2>Preparing your secure room</h2>
            <p>The voice agent will join automatically.</p>
          </div>
        ) : null}

        {(stage === "connecting" || stage === "live") &&
        credentials &&
        choices ? (
          <VoiceSession
            credentials={credentials}
            choices={choices}
            labels={{
              title: product.title,
              agentName: product.eyebrow,
              cameraAllowed: product.cameraAllowed,
            }}
            onConnected={() =>
              setStage((current) => transitionVoiceFlow(current, "connected"))
            }
            onDisconnected={() => finish()}
            onError={(reason) => finish(reason)}
          />
        ) : null}

        {stage === "completed" ? (
          <div className="center-state completion">
            <span className="completion-mark" aria-hidden="true">
              ✓
            </span>
            <h2>Session complete</h2>
            <p>Your LiveKit connection has ended.</p>
            <div className="button-row">
              <button className="button primary" type="button" onClick={restart}>
                Start another session
              </button>
              <Link className="button secondary" href="/">
                Choose another product
              </Link>
            </div>
          </div>
        ) : null}
      </section>
    </main>
  );
}
