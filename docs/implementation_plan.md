# Unified Voice AI Platform — Implementation Plan

Aaptor v2 (AI Interviewer) + Racko-style Voice CS. Shared models, isolated serving, single-GPU pilot scaling to multi-pool production.

---

## 1. Interview question generation — technical design (Stage 1 + Stage 2)

### Stage 1 — Interview Plan Generator (runs once per candidate-role pair, cached)

Input: job description + candidate resume
Output: a **structured JSON outline** — not questions, just topics/phases/sequencing

This must use **constrained/structured generation**, not free-text prompting, so the outline is always valid and parseable downstream. vLLM's current API (post v0.12.0) is `structured_outputs` with a JSON schema — the older `guided_json` parameter is deprecated:

```python
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="not-needed")

outline_schema = {
    "type": "object",
    "properties": {
        "phases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "topics": {"type": "array", "items": {"type": "string"}},
                    "source": {"type": "string", "enum": ["resume", "jd", "generic"]}
                },
                "required": ["name", "duration_minutes", "topics", "source"]
            }
        }
    },
    "required": ["phases"]
}

response = client.chat.completions.create(
    model="Qwen/Qwen3-4B-Instruct-2507",
    messages=[
        {"role": "system", "content": "You are an interview planner. Output only the outline structure."},
        {"role": "user", "content": f"JD:\n{jd_text}\n\nResume:\n{resume_text}"}
    ],
    extra_body={"structured_outputs": {"json": outline_schema}}
)
```

Backend note: vLLM auto-selects between `xgrammar` (best for longer generations, benefits from schema caching) and `guidance` (best time-to-first-token on unique/dynamic schemas) — for this use case, schemas are reused across every interview, so `xgrammar`'s caching advantage applies; no need to force a backend manually.

### Stage 2 — Live Question Generator (runs every turn)

Input: current outline phase + running transcript
Output: the actual question text, grounded in what the candidate just said

This stays free-text (not JSON-constrained) since it's natural conversational output. It reads the current phase's topics from Stage 1's output and the last 1–2 candidate turns, decides "probe deeper" vs "advance to next phase," and generates accordingly.

### Shared methodology library (sector-agnostic, never grows with sector count)

- STAR behavioral question templates
- Rubric structure (specificity / ownership / outcome — filled in per-JD at runtime, not stored per sector)
- Anti-bias guardrail prompt fragments
- Default phase timing/weighting

---

## 2. Project structure (monorepo)

```
voice-ai-platform/
├── apps/
│   └── voice-frontend/             # Neutral internal integration demo
│
├── packages/
│   └── voice-ui/                  # Product-neutral LiveKit UI primitives
│
├── services/
│   ├── backend-api/               # FastAPI — auth, session mgmt, scoring, tool routing
│   │   ├── routers/
│   │   ├── models/                 # Pydantic schemas incl. outline_schema, scorecard_schema
│   │   └── db/                     # Mongo/Postgres access layer
│   │
│   ├── voice-agent/                # Python, livekit-agents SDK
│   │   ├── aaptor_agent.py         # Interview flow orchestrator (Stage 1 + Stage 2)
│   │   ├── racko_agent.py          # CS flow orchestrator (context engine + tools)
│   │   └── shared/                 # Shared STT/TTS/LLM client wrappers
│   │
│   ├── model-serving/
│   │   ├── stt/                    # Nemotron 3.5 ASR / IndicConformer configs
│   │   ├── tts/                    # Kokoro / CosyVoice configs
│   │   └── llm/                    # vLLM serve configs, schemas (outline_schema.json etc.)
│   │
│   └── context-engine/             # CS-only — RAG retrieval, KG, context assembler
│
├── infra/
│   ├── docker/                     # Per-service Dockerfiles
│   ├── k8s/                        # Manifests: aaptor-gpu-pool/, cs-gpu-pool/, shared/
│   ├── helm/                       # vLLM Production Stack values, Riva Helm values
│   └── terraform/                  # Cloud infra as code (if applicable)
│
├── notebooks/
│   └── voice_stack_colab_test.ipynb  # Model validation notebook (already built)
│
├── docs/
│   ├── production_architecture_context.md  # Master architecture doc (already built)
│   ├── interview_generation_design.md      # This section, expanded
│   └── gpu_sizing_guide.md
│
└── proctoring/                     # Face detect, audio anomaly, tab/focus, screen capture
```

Branded Aaptor and Racko applications live in separate product repositories and
consume the platform APIs and versioned shared voice packages.

---

## 3. Phased roadmap

### Phase 0 — Research & validation (current)
- Colab notebook testing: STT, TTS, LLM individually
- Stage 1 outline generation prototype (structured outputs) tested against 5–10 real JD/resume pairs
- Stage 2 live question generation quality check against real transcripts

### Phase 1 — Single-GPU pilot
- One GPU box (RTX 4090 / A10G / L4), all models co-located
- FastAPI + LiveKit + Mongo + Redis stood up
- Aaptor: full interview flow end-to-end, 1 concurrent session
- Racko: basic CS flow end-to-end, 1 concurrent call
- Proctoring: face detect + tab/focus minimum viable

### Phase 2 — Growth (isolated pools)
- Split into Aaptor GPU pool + CS GPU pool (per earlier architecture)
- Kubernetes + KEDA/HPA autoscaling live
- Reasoning-tier LLM (30B-A3B or API fallback) added for complex turns
- Admin consoles fully functional

### Phase 3 — Scale
- Multi-node GPU clusters, tensor/pipeline parallelism
- Full observability stack (OpenTelemetry + Grafana)
- SLA-backed CS product

---

## 4. Azure DevOps sprint plan

Azure Boards terminology: **iteration paths = sprints** (time-boxed), defined at the project level, then selected per team. Backlog items get dragged into a sprint during sprint planning, which updates their Iteration Path automatically.

### Suggested setup
- **Area paths**: `Aaptor`, `Racko-CS`, `Shared-Infra` — so both products' work is filterable independently within one project
- **Iteration paths**: `Sprint 1` ... `Sprint N`, 2-week cadence recommended for this stage
- **Work item hierarchy**: Epic → Feature → User Story/Backlog Item → Task (Scrum process) or Epic → Feature → PBI → Task (Agile process) — pick one process template when creating the Azure DevOps project, don't mix

### Epics (create these first, one per major section above)
1. `EPIC: Model validation (Colab)`
2. `EPIC: Interview plan/question generation pipeline`
3. `EPIC: Single-GPU pilot deployment`
4. `EPIC: CS context engine (RAG)`
5. `EPIC: Proctoring`
6. `EPIC: Admin consoles`
7. `EPIC: Multi-pool production scaling`

### Sprint 1 — Model validation
- [ ] Task: Run STT (Nemotron) test in Colab, log WER on sample Indian-accent audio
- [ ] Task: Run TTS (Kokoro) test in Colab, subjective quality check
- [ ] Task: Run LLM (Qwen3-4B-AWQ) via vLLM in Colab, measure latency
- [ ] Task: Set up `structured_outputs` JSON schema for interview outline, validate against 5 JD/resume pairs
- [ ] Task: Document VRAM usage per model, confirm single-GPU fit

### Sprint 2 — Core pipeline (backend + voice agent skeleton)
- [ ] Task: FastAPI backend skeleton — auth, session model, Mongo schema (`tests`, `candidates`, `sessions`, `turns`)
- [ ] Task: LiveKit self-hosted server — single-node setup
- [ ] Task: `voice-agent` service — wire STT → LLM → TTS in one script, no LiveKit yet, measure round-trip latency
- [ ] Task: Integrate `voice-agent` into LiveKit `VoicePipelineAgent`

### Sprint 3 — Aaptor interview flow
- [ ] Task: Implement Stage 1 (Interview Plan Generator) as a backend endpoint
- [ ] Task: Implement Stage 2 (Live Question Generator) inside `aaptor_agent.py`
- [ ] Task: Wire follow-up/probe-vs-advance decision logic
- [ ] Task: Candidate web app — join session, WebRTC audio, basic UI
- [ ] Task: Scoring engine — generate scorecard from JD-derived rubric

### Sprint 4 — Racko CS flow (parallel track if resourced separately)
- [ ] Task: Context engine — document retrieval (RAG) minimum viable
- [ ] Task: Tool & integration layer — account/billing mock tools
- [ ] Task: `racko_agent.py` — orchestrator wiring context + tools + LLM
- [ ] Task: CS web client — basic call UI

### Sprint 5 — Proctoring + admin
- [ ] Task: Face detection integration (reuse existing Aaptor code per original doc)
- [ ] Task: Tab/focus switch detection
- [ ] Task: Admin console — test builder, candidate manager
- [ ] Task: Results dashboard — transcript, recording, scorecard view

### Sprint 6 — Pilot hardening
- [ ] Task: Single-GPU deployment via Docker Compose, documented runbook
- [ ] Task: End-to-end latency budget validation against target (<1.2s p95)
- [ ] Task: Error handling / reconnect logic for dropped WebRTC sessions
- [ ] Task: Basic observability — logs + latency metrics

### Later sprints (Phase 2/3 — create as backlog items, schedule once Phase 1 ships)
- Kubernetes migration, isolated GPU pools, KEDA/HPA autoscaling
- Reasoning-tier LLM integration + routing logic
- IndicConformer / native-language interview mode
- Multi-region LiveKit, InfiniBand/RoCE networking for multi-node vLLM

---

## 5. Open items to track as spikes (not yet decided)

- Qwen3.8-9B-Distill vs Qwen3-4B — needs head-to-head test before default model changes
- Sarvam Bulbul (API-only) vs open-source Indic TTS — quality/cost tradeoff for native-language clients
- CI/CD pipeline choice (not yet specified)
- Disaster recovery RTO/RPO targets (not yet specified)
