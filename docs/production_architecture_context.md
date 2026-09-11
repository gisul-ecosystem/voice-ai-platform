# Unified Voice AI Production Architecture — Context for Diagram Generation

## System overview

One company, two voice AI products, sharing a model layer but isolated at the serving layer:

- **Product A — Aaptor v2**: AI interviewer platform (candidate-facing, scheduled sessions, 15–40 min)
- **Product B — Racko-style Voice CS**: customer support voice agent (bursty traffic, 2–8 min calls)

Both are built on LiveKit (self-hosted WebRTC) + FastAPI + a shared AI inference layer. Each client can choose **API mode** (cloud providers) or **on-prem mode** (zero data egress) independently, per product, per client.

---

## Layer 1 — Real-time Voice Layer

- **LiveKit Gateway** (self-hosted SFU): media rooms, session/participant management, data channel, recording egress
- **VAD + Turn Detection**: streaming voice activity detection, end-of-turn detection, barge-in/interrupt handling
- **Streaming STT**: converts caller audio to text in real time (model choice below)
- **Audio buffer + barge-in handling**: manages partial vs final transcripts, interrupt logic
- **Streaming TTS**: converts LLM output to speech, streamed back as it's generated
- Target: first-audio latency < 300ms, end-to-end response < 1.2s (p95)

## Layer 2 — Conversation & Intelligence Layer

- **Conversation Manager**: session state, context window, memory, policy/guardrails, response streaming
- **Intent & Router (lightweight)**: intent classification, complexity scoring, routes to correct model tier
- **LLM Router (model ensemble)**: served via vLLM
  - Fast/normal tier → Qwen3-8B
  - High-reasoning tier → Qwen3-30B-A3B (MoE, ~3B active params/token — cheap to run despite size)
  - Mid tier → Qwen3-14B (optional, fill gap between fast and high-reasoning)
- **AI Orchestrator (agent core)**: for Aaptor — plan interview flow, select next question, follow-up logic, predefined-mode sequencer. For CS — plan + tool selection, escalation decisioning
- **Specialized modules**:
  - Aaptor: scoring engine, AI scorecard generation
  - CS: account/billing module, negotiation/offer module (where applicable)

## Layer 3 — Context Engine (CS-specific, optional for Aaptor)

- Query understanding: rewrite, entity extraction, term normalization, language detection
- Live platform integration (structured DB facts): server status, order/ticket lookups
- Document retrieval (hybrid RAG): policy/knowledge base
- Knowledge graph (optional): customer ↔ service relationships
- Context assembler: dedupe, re-rank, freshness check → verified context passed to LLM

## Layer 4 — Tool & Integration Layer

- Account tools, billing tools, order tools, support tools — invoked by the orchestrator
- AuthN/AuthZ, request validation, rate limiting, audit logging, idempotency
- Routed through one shared AI Gateway for both products, with per-product rate limits and priority queues

## Layer 5 — Data & Storage Layer

- **MongoDB** (or Postgres for CS if relational fits better): sessions, turns, scores, candidates/tickets, flags
- **Vector DB** (Qdrant/Milvus): embeddings for RAG (CS knowledge base; optional for Aaptor)
- **Blob storage**: S3 (API mode) / SeaweedFS (on-prem mode) — recordings, transcripts, screen captures
- **Cache layer** (Redis): session state, hot lookups, rate-limit counters

## Layer 6 — Infrastructure

- **Self-hosted / hybrid cloud**, GPU-backed
- **Two separate GPU pools/node groups** — one per product — even though model weights are shared:
  - Isolation reason: CS traffic is bursty and SLA-critical; Aaptor traffic is scheduled and longer-lived. A spike in one must not starve the other.
- Autoscaling per pool (HPA/KEDA on Kubernetes, or Ray Serve for the model-serving layer specifically)
- Shared **model registry** (one version of each fine-tuned STT/TTS checkpoint, consumed by both pools)

## Layer 7 — Security & Governance

- JWT/API key auth, RBAC, tool permissions (read/write gated separately)
- Confirmation gate for critical actions (refunds, cancellations, score overrides)
- Data privacy: PII protection, encryption at rest/in transit
- Audit log of all actions
- Per-client mode enforcement (on-prem clients' audio must never leave their infra — enforced at the gateway, not just by config)

## Layer 8 — Human Support & Escalation

- Human agent console: full transcript + conversation handoff
- Ticket creation (automatic or manual)
- Live co-browse / screen share (CS only, optional)
- Knowledge push-to-agent

## Layer 9 — Observability & Quality

- OpenTelemetry tracing (real-time + async flows)
- Grafana dashboards (latency, error rate, concurrency per pool)
- Alerts/notifications (PagerDuty/email/Slack)
- Quality monitoring: transcripts, scores, feedback loop
- Cost & usage tracking, broken out **per model, per product** (so Aaptor vs CS cost is separately visible even though models are shared)

---

## Model stack (both products draw from this shared layer)

### Speech-to-Text (understanding)
| Use case | Model | Mode |
|---|---|---|
| Indian-accent English (primary) | Nemotron 3.5 ASR 0.6B | On-prem + API |
| Native Hindi/Tamil/Telugu (CS, Aaptor roadmap) | AI4Bharat IndicConformer 600M | On-prem |
| Code-mixed Hinglish fallback | Whisper Large-v3 / IndicWhisper | On-prem |

### Text-to-Speech (speaking)
| Use case | Model | Mode |
|---|---|---|
| Fast Indian-English voice | Kokoro-82M | On-prem |
| Accent-quality Indian-English | CosyVoice 2 | On-prem |
| Native Indic speech output | AI4Bharat Indic Parler-TTS / Sarvam Bulbul | On-prem (Parler) / API-only (Bulbul) |
| Premium API-mode voice | ElevenLabs Flash v2.5 / Cartesia Sonic 3 | API |

### LLM
| Tier | Model | Served via |
|---|---|---|
| Fast/normal | Qwen3-8B | vLLM |
| Mid | Qwen3-14B | vLLM |
| High reasoning | Qwen3-30B-A3B (MoE) | vLLM |
| API mode | GPT-4o / Claude / Gemini | Provider API |

---

## End-to-end data flow (single turn)

1. Candidate/customer speaks → LiveKit Gateway receives audio over WebRTC
2. VAD/turn detection identifies end of utterance
3. Streaming STT (Nemotron or IndicConformer) → partial + final transcript
4. Transcript → Conversation Manager → Intent/Router
5. Router selects LLM tier → (Aaptor: Orchestrator picks next question / follow-up) or (CS: Orchestrator + Context Engine assemble retrieval context) → LLM generates response
6. Response streamed to TTS (Kokoro/CosyVoice/Bulbul) as soon as first sentence is ready
7. Audio streamed back to candidate/customer via LiveKit
8. Turn logged to MongoDB; proctor/quality signals logged in parallel
9. Observability layer captures latency at every hop (OpenTelemetry spans)

---

## Deployment/isolation principle (the key architectural decision)

**Same model weights. Separate serving deployments.**

- One model registry, one fine-tuning/eval pipeline, one team owning "the Indian-accent STT" and "the Indian-English TTS voice"
- Two independent GPU pools + autoscaling groups + rate limits, tagged by product, behind a shared AI Gateway
- Each client's on-prem/API mode choice is enforced independently per product

---

## Target latency budget (from real-time layer)

| Stage | Target |
|---|---|
| STT first token | 80–200ms |
| LLM first token | 100–300ms |
| Tool/API call (if needed) | 150–450ms |
| TTS first audio | 100–200ms |
| **End-to-end (p95)** | **700–1200ms** |

---

## Tech stack summary

- **Voice/RTC**: LiveKit, WebRTC, Opus
- **STT**: Nemotron 3.5 ASR, AI4Bharat IndicConformer, faster-Whisper (fallback)
- **LLM**: Qwen3 family (8B/14B/30B-A3B) via vLLM; GPT-4o/Claude/Gemini for API mode
- **TTS**: Kokoro, CosyVoice 2, Indic Parler-TTS / Sarvam Bulbul, ElevenLabs/Cartesia (API mode)
- **Backend**: FastAPI (Python), gRPC/websocket internal
- **Data**: MongoDB, Qdrant/Milvus (vectors), Redis (cache), S3/SeaweedFS (blob)
- **Infra**: Kubernetes, Docker, Ray Serve or Triton for model serving, KEDA/HPA autoscaling
- **Observability**: OpenTelemetry, Grafana, Prometheus
- **Frontend**: Next.js (candidate/customer), admin panel

---

## Notes for diagram generation

- Structure as numbered layers top to bottom (as above): Real-time Voice → Conversation & Intelligence → Context Engine → Tool & Integration → Data & Storage → Infrastructure → Security & Governance → Human Support → Observability
- Show **two parallel GPU pool boxes** (Aaptor pool / CS pool) both pointing back to a single "Shared Model Registry" box, to visually capture the "same model, separate deployment" decision
- Show API mode vs on-prem mode as two side-by-side paths under the model layer, per product
- Include a legend distinguishing sync (real-time voice) vs async (ticketing, escalation, observability) flows
