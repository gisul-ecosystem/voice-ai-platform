# AI Interviewer Readiness Sprint Plan

## Sprint summary

- Duration: 2 weeks
- Team: Abhijeeth, Aditya, Akshay, Ujwal
- Planned capacity: 49 story points
- Sprint goal: Produce a reproducible, measured AI interview using the current cloud-provider path and prove the feasibility of self-hosted inference on target hardware.

## Abhijeeth — Speech accuracy and latency (13 SP)

### PBI A1: Baseline speech and latency harness (3 SP)

Tasks:
- Define measurements for speech-end-to-final-transcript, transcript-to-first-token, first-token-to-first-audio, and speech-end-to-first-audio.
- Capture p50, p95, error rate, word error rate, and interruption recovery.
- Build a repeatable test set covering silence, noise, accents, short answers, long answers, and interruptions.

Acceptance criteria:
- Results can be reproduced from a documented command.
- Every run records provider, model, language, audio properties, and tuning parameters.
- Baseline measurements are saved without exposing candidate PII or API keys.

### PBI A2: Sarvam, VAD, and endpointing tuning (5 SP)

Tasks:
- Tune minimum speech duration, silence duration, endpointing delay, and interruption thresholds.
- Validate partial/final transcript handling and deduplication.
- Test noisy audio, pauses, filler words, and candidate self-correction.
- Document recommended English and Indian-accent settings.

Acceptance criteria:
- No duplicate final transcript turns.
- Normal pauses do not prematurely end candidate answers.
- Long silence does not leave the interview blocked indefinitely.
- Accuracy and latency changes are compared with the baseline.

### PBI A3: Streaming LLM-to-TTS and interruption tests (5 SP)

Tasks:
- Verify token streaming from OpenAI into ElevenLabs TTS.
- Measure time to first synthesized audio.
- Test candidate interruption, agent cancellation, and clean resume behavior.
- Prevent stale audio from playing after interruption.

Acceptance criteria:
- Speech-end-to-first-audio reaches p50 at or below 1.2 seconds and p95 at or below 2 seconds under agreed staging conditions.
- Interrupted responses stop promptly without overlapping the candidate.
- A staging trace identifies latency across STT, LLM, and TTS.

## Aditya — Questions and follow-up intelligence (13 SP)

### PBI B1: Versioned competency and question contract (5 SP)

Tasks:
- Define a versioned schema for competencies, lead questions, probes, evidence requirements, and scoring anchors.
- Map seniority and difficulty to expected response depth.
- Keep lead questions fixed for comparable candidate evaluation.
- Validate generated plans with a strict JSON schema.

Acceptance criteria:
- Invalid or incomplete plans are rejected or safely regenerated.
- Every question maps to a competency and expected evidence.
- Plan version and prompt version are persisted with the interview attempt.
- Question limits fit the configured interview duration.

### PBI B2: Evidence-aware structured follow-up engine (5 SP)

Tasks:
- Classify answers as sufficient, partial, unclear, off-topic, or unsupported.
- Select a bounded probe based on missing evidence.
- Track previously collected evidence to avoid repeated questions.
- Enforce `maxProbesPerPhase` and remaining-time limits.

Acceptance criteria:
- Follow-ups request specific missing evidence instead of producing generic prompts.
- The engine never exceeds the configured probe limit.
- The flow advances when sufficient evidence exists or the probe budget is exhausted.
- LLM failure produces a safe fallback and does not terminate the session.

### PBI B3: Quality, consistency, and red-team evaluation (3 SP)

Tasks:
- Create representative answer fixtures for strong, weak, vague, contradictory, and adversarial responses.
- Test question relevance, repetition, prohibited topics, prompt injection, and scoring consistency.
- Define a human-review rubric for generated questions and probes.

Acceptance criteria:
- No prohibited or discriminatory question appears in the approved test set.
- Prompt injection in a resume or candidate answer cannot alter system policy.
- Evaluation produces repeatable pass/fail evidence for each release.

## Akshay — Platform reliability and contract verification (10 SP)

### PBI C1: Repair Linux CI dependency reproducibility (2 SP)

Tasks:
- Correct the backend LiveKit server SDK dependency.
- Resolve the frontend native optional-dependency installation failure.
- Pin or lock dependencies required for repeatable clean builds.

Acceptance criteria:
- Python tests pass on a clean Ubuntu runner.
- Frontend lint, typecheck, tests, and build pass on a clean Ubuntu runner.
- Paid provider tests remain explicitly opt-in.

### PBI C2: Idempotent lifecycle and LiveKit reconciliation (5 SP)

Tasks:
- Verify valid interview lifecycle transitions and duplicate-event handling.
- Validate invitation reserve, commit, release, and retry behavior.
- Reconcile backend session status with LiveKit room and participant state.
- Verify ordered, idempotent transcript turn persistence.

Acceptance criteria:
- Repeated join requests with the same idempotency key return the same session.
- Failed room creation releases the invitation reservation safely.
- Duplicate turns do not create duplicate transcript entries.
- Invalid lifecycle transitions return explicit outcomes and create no partial state.

### PBI C3: Scheduling, invitation, and failure-path contract tests (3 SP)

Tasks:
- Add tests for scheduling, invitation preview, consent, join windows, and session creation.
- Test expired, reused, malformed, early, and late invitations.
- Test backend, MongoDB, LiveKit, and provider failure responses.

Acceptance criteria:
- Public and internal API contracts have automated positive and negative tests.
- Candidate PII and secrets do not appear in LiveKit metadata or logs.
- Failure tests confirm that no orphan room, session, or invitation reservation remains.

## Ujwal — Deployment and self-hosted model integration (13 SP)

### PBI D1: Staging deployment, secrets, and startup validation (3 SP)

Tasks:
- Own deployment of the backend API, interviewer worker, frontend reference app, MongoDB connectivity, and LiveKit integration.
- Configure secrets through the deployment environment; do not commit them to source control.
- Add startup checks for required production configuration and service-to-service authentication.
- Document deployment, rollback, health checks, and log access.

Acceptance criteria:
- All required services start from a clean staging deployment.
- Missing required production secrets fail startup clearly.
- Health checks distinguish application health from dependency readiness.
- A rollback procedure is documented and tested.

### PBI D2: Hardware, licence, and model decision record (2 SP)

Tasks:
- Record target hardware, concurrency, memory, quantization, licence, and deployment constraints.
- Define evaluation criteria for self-hosted STT, LLM, and TTS.
- Document the cloud-provider fallback strategy.

Acceptance criteria:
- The decision record names supported hardware and measurable release thresholds.
- Model licences are reviewed for the intended commercial use.
- No model is selected solely from published benchmark claims.

### PBI D3: Nemotron 3.5 streaming STT adapter spike (3 SP)

Tasks:
- Prototype the self-hosted STT adapter behind the existing provider abstraction.
- Test streaming partial/final events and endpointing behavior.
- Measure accuracy, real-time factor, memory, and concurrency on target hardware.

Acceptance criteria:
- The prototype does not require changes to interview business logic.
- Benchmark results use the same corpus and metrics as the cloud STT baseline.
- Limitations and a productionization estimate are documented.

### PBI D4: Qwen3-8B vLLM non-thinking spike (3 SP)

Tasks:
- Serve the model through an OpenAI-compatible endpoint.
- Disable or constrain thinking output for conversational latency.
- Test strict structured output, prompt adherence, first-token latency, and concurrency.

Acceptance criteria:
- Existing LLM provider interfaces can invoke the model.
- The model returns valid interview decisions for the agreed evaluation set.
- Latency, throughput, memory, quality, and failure behavior are documented.

### PBI D5: Kokoro/CosyVoice benchmark and staging E2E (2 SP)

Tasks:
- Compare candidate TTS models for first-audio latency, naturalness, streaming behavior, pronunciation, licence, and hardware use.
- Run one complete staging interview through candidate audio, STT, LLM, TTS, and transcript persistence.
- Record deployment and model bottlenecks.

Acceptance criteria:
- At least one self-hosted TTS candidate has measured results on target hardware.
- One recorded staging run completes the full voice pipeline.
- The result includes a recommendation, risks, and next-step estimate.

## Shared release gates

### Build

GitHub CI is green on Ubuntu using a clean dependency installation and pinned Python packages.

### Media

One recorded staging run completes candidate audio → STT → LLM → TTS → durable transcript.

### Latency

Speech-end-to-first-audio is at or below 1.2 seconds p50 and 2 seconds p95 under the agreed test conditions.

### Interview quality

The flow uses fixed lead questions, bounded evidence-aware probes, strict schemas, and produces no prohibited questions in the red-team suite.

### Self-hosted feasibility

At least one STT, LLM, and TTS candidate is measured on target hardware. Every recommendation includes quality, latency, throughput, memory, licence, and operational evidence.

## Suggested sprint sequence

### Days 1–2

- Confirm acceptance criteria and test datasets.
- Repair CI.
- Establish cloud-provider latency and quality baselines.
- Complete target-hardware and model decision record.
- Prepare the staging deployment.

### Days 3–6

- Tune Sarvam, VAD, and endpointing.
- Implement the versioned interview contract and follow-up engine.
- Verify lifecycle idempotency and failure handling.
- Run self-hosted STT and LLM spikes.

### Days 7–8

- Complete interruption and streaming tests.
- Run quality and red-team evaluation.
- Benchmark self-hosted TTS.
- Deploy integrated changes to staging.

### Days 9–10

- Run the complete staging interview and collect evidence.
- Fix release-blocking defects.
- Review metrics against release gates.
- Demonstrate results and create next-sprint backlog items.

## Out of scope for this sprint

- Transactional email automation
- Full administrator monitoring UI
- Production scorecard worker and feedback release
- LiveKit recording and egress
- Broad multilingual rollout
- Production rollout of self-hosted inference without benchmark approval

## Research references

- [LiveKit turn detection and endpointing](https://docs.livekit.io/agents/logic/turns/tuning/)
- [Sarvam LiveKit production guidance](https://docs.sarvam.ai/api/integration/livekit-production-best-practices)
- [US OPM structured interview guide](https://www.opm.gov/policy-data-oversight/assessment-and-selection/structured-interviews/guide/)
- [NVIDIA Nemotron 3.5 ASR](https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b)
- [Qwen3-8B](https://huggingface.co/Qwen/Qwen3-8B)
- [CosyVoice](https://github.com/FunAudioLLM/CosyVoice/)
- [Azure DevOps sprint capacity](https://learn.microsoft.com/en-us/azure/devops/boards/sprints/set-capacity)
