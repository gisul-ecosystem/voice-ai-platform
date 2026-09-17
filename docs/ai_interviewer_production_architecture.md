# AI Interviewer Production Architecture

Status: accepted target architecture  
Scope: Aaptor candidate interviews using OpenAI LLM, Sarvam STT, ElevenLabs TTS, and LiveKit

## Decision

The backend is authoritative for interview identity, invitations, provider policy,
context, lifecycle, persistence, and completion. LiveKit is the real-time media
plane. The voice worker performs latency-sensitive turn orchestration and emits
durable events back to the backend.

The generic `apps/voice-frontend` remains an internal integration demo.
The branded Aaptor product remains in its separate repository and consumes
versioned, product-neutral voice packages from this platform repository.

## Trust boundaries

1. Browser credentials are signed interview invitations and short-lived,
   room-scoped LiveKit participant tokens.
2. Next.js BFF calls FastAPI with a separate service credential.
3. Workers call FastAPI with a worker service credential.
4. Provider credentials are injected into backend/worker processes from
   environment-managed secrets. They are never accepted from browsers or stored
   in LiveKit metadata.
5. LiveKit dispatch metadata contains opaque IDs only: interview session,
   context, tenant, and correlation IDs.

## Interview lifecycle

`scheduled -> ready -> joining -> live -> completing -> completed`

Terminal alternatives are `expired`, `abandoned`, and `failed`. Every transition
is validated by backend policy and recorded as an audit event. Model output may
recommend a question decision, but it cannot directly mutate lifecycle state.

## Data model

- Interview: tenant, role, schedule, policy, context reference.
- Attempt: candidate, invitation digest, attempt number, status.
- Live session: room, dispatch, correlation ID, timestamps, disconnect reason.
- Turn: stable ID, speaker, final text, timing, phase and topic evidence.
- Scorecard: asynchronous rubric results with model/prompt provenance.
- Audit event: actor, action, object, timestamp and non-PII metadata.

Raw documents live in encrypted object storage. Parsed context and durable
interview records live in the application database. Redis may be used for
idempotency, quotas, hot state, and distributed coordination, but never as the
only durable record.

## Provider pipeline

- OpenAI: strict schema-constrained planning; streamed question generation;
  bounded retries that respect `Retry-After`; project-level spend limits.
- Sarvam: `api-subscription-key` authentication and `saaras:v3-realtime`
  WebSocket partial/final transcription for live sessions.
- ElevenLabs: Flash v2.5 HTTP output streaming when text is complete, upgraded
  to WebSocket input streaming when LLM tokens are forwarded incrementally.

Connections are pooled, cancellation-aware, deadline-bound, and instrumented.
Paid POST operations are not blindly replayed after ambiguous failures.

## Product applications

The separate Aaptor candidate application contains invitation landing, organization identity,
consent, compatibility checks, prejoin, live interview, reconnection, help, and
completion. Recruiter-owned JD/resume upload, extraction review, scheduling,
invitations, and results belong to an admin application or API.

`packages/voice-core` owns headless LiveKit connection, device, reconnect, token
refresh, and event state. `packages/voice-ui` owns accessible shared controls and
compositions. Product branding and copy remain in Aaptor.

## Production gates

- Authenticated staging browser-to-worker media E2E passes.
- OpenAI, Sarvam, and ElevenLabs happy-path smoke tests pass without logging PII.
- Reconnect, provider outage, worker restart, malformed model response, and
  explicit completion tests pass.
- Accessibility checks cover keyboard, screen reader, zoom, reduced motion,
  device permission failure, and short/mobile viewports.
- Load and soak tests establish p95 latency, completion success, concurrency,
  abandonment, provider cost, and retry amplification.
- OpenTelemetry correlation spans browser, BFF, backend, LiveKit job, worker,
  and provider calls without names, documents, transcripts, tokens, or keys.

## Source references

- [LiveKit explicit dispatch](https://docs.livekit.io/agents/server/agent-dispatch/)
- [LiveKit custom deployment](https://docs.livekit.io/deploy/custom/deployments/)
- [OpenAI production practices](https://developers.openai.com/api/docs/guides/production-best-practices)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Sarvam realtime STT](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming)
- [ElevenLabs latency optimization](https://elevenlabs.io/docs/eleven-api/guides/how-to/best-practices/latency-optimization)
