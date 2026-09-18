# AI Interviewer Production Architecture

Status: accepted target architecture + as-built interviewer brain notes  
Scope: Aaptor candidate interviews using OpenAI LLM, Sarvam STT, ElevenLabs TTS, and LiveKit

## Decision

The backend is authoritative for interview identity, invitations, provider policy,
context, lifecycle, persistence, scoring, and completion. LiveKit is the real-time media
plane. The voice worker performs latency-sensitive turn orchestration and emits
durable events back to the backend.

The interviewer **brain** (JD/resume intelligence, blueprint compiler, 3-layer
memory, policy engine, transcript, advisory scorecard) lives inside
`services/backend-api` + `services/voice-agent/products/interviewer`. Do not
introduce a separate context-engine microservice for Aaptor unless measured
scale or ownership requires it.

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
   context, definition, tenant, and correlation IDs.

## Interview lifecycle

`scheduled -> ready -> joining -> live -> completing -> completed`

Terminal alternatives are `expired`, `abandoned`, and `failed`. Every transition
is validated by backend policy and recorded as an audit event. Model output may
phrase questions, but the **policy engine** (not the LLM alone) decides next
action, depth, probe limits, and close. Lifecycle state mutations remain backend-owned.

On `completed`, backend generates an advisory evidence-linked scorecard
(`human_review_status=pending`). Hiring decisions remain human-owned; review and
override APIs/UI are not shipped yet.

## As-built data plane (interviewer brain)

```text
Creator demo UI / BFF
  -> backend-api: ingest, extract, compile/publish, schedule
  -> Mongo: interview_definitions (immutable) + context + invitation
  -> candidate join -> live session (definition_id)
  -> voice-agent: load definition, policy next-action, phrase via LLM
  -> BrainSessionBridge: RAM checkpoint -> Redis hot snapshot -> Mongo durable
  -> interview_turns (full transcript) + questions/answers/evidence/snapshots
  -> completed -> interview_scorecards (insert-once AI card)
```

Collections in use:

- `interview_contexts`, `interview_definitions`, `interview_sessions`,
  `interview_turns`, `interview_invitations`
- `interview_questions`, `interview_answers`, `interview_evidence`,
  `interview_brain_snapshots`, `interview_scorecards`

Redis (optional hot layer): key `interview:brain:{session_id}`;
`REDIS_URL` + `INTERVIEW_BRAIN_REDIS_TTL_SECONDS` (default 6h). Never the only
durable store — Mongo remains source of truth.

Raw documents: text-layer PDF/DOCX/TXT ingest today (OCR pending). Long-term
target remains encrypted object storage for originals.

## Data model

- Interview: tenant, role, schedule, policy, context reference, definition_id.
- Attempt: candidate, invitation digest, attempt number, status.
- Live session: room, dispatch, correlation ID, timestamps, disconnect reason.
- Turn: stable ID, speaker (`candidate`|`agent`), final text, timing, phase/topic.
- Brain records: question ledger, answer linkage, evidence, versioned snapshots.
- Scorecard: asynchronous rubric results with evidence refs and model provenance.
- Audit event: actor, action, object, timestamp and non-PII metadata.

## Provider pipeline

- OpenAI: strict schema-constrained planning; streamed question generation;
  bounded retries that respect `Retry-After`; project-level spend limits.
- Sarvam: `api-subscription-key` authentication and `saaras:v3-realtime`
  WebSocket partial/final transcription for live sessions.
- ElevenLabs: Flash v2.5 HTTP output streaming when text is complete, upgraded
  to WebSocket input streaming when LLM tokens are forwarded incrementally.

Connections are pooled, cancellation-aware, deadline-bound, and instrumented.
Paid POST operations are not blindly replayed after ambiguous failures.

Milestone 5 (not done): session-pinned voice, TTS preflight, and no silent
voice switch on provider failure.

## Product applications

The separate Aaptor candidate application contains invitation landing, organization identity,
consent, compatibility checks, prejoin, live interview, reconnection, help, and
completion. Recruiter-owned JD/resume upload, extraction review, scheduling,
invitations, and results belong to an admin application or API.

`packages/voice-core` owns headless LiveKit connection, device, reconnect, token
refresh, and event state. `packages/voice-ui` owns accessible shared controls and
compositions. Product branding and copy remain in Aaptor.

In this monorepo demo path, `apps/voice-frontend` covers schedule/setup, ingest,
and candidate journey; transcript/scorecard BFF proxies exist without a full
recruiter results console yet.

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
- Brain gates: definition attached on schedule, policy mode active when
  definition present, turns durable for every spoken utterance, scorecard cites
  evidence or marks `not_assessed`.

## Source references

- End-to-end brain plan (as-built §1A / §3): `docs/ai_interviewer_brain_end_to_end_plan.md`
- [LiveKit explicit dispatch](https://docs.livekit.io/agents/server/agent-dispatch/)
- [LiveKit custom deployment](https://docs.livekit.io/deploy/custom/deployments/)
- [OpenAI production practices](https://developers.openai.com/api/docs/guides/production-best-practices)
- [OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
- [Sarvam realtime STT](https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming)
- [ElevenLabs latency optimization](https://elevenlabs.io/docs/eleven-api/guides/how-to/best-practices/latency-optimization)
