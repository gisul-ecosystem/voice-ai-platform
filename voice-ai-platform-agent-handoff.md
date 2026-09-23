# Voice AI Platform — Agent Handoff Brief

## What this repo is

Monorepo for a voice AI platform with two products:

| Product | Role | Entry |
|---|---|---|
| **Aaptor** | AI interviewer (main focus of recent work) | `python aaptor_agent.py start` in `services/voice-agent` |
| **Racko** | Voice customer support | `python racko_agent.py start` |

**Shared runtime:** LiveKit workers + STT/LLM/TTS clients.  
**Pilot topology:** multi-laptop LAN.  
**Production-ish LiveKit:** often `wss://livekit.gisul.co.in`.

**Repo:** `gisul-ecosystem/voice-ai-platform`  
**Local path:** `c:\Users\ACER\voice-ai-platform`

---

## Architecture — live interview

```text
Frontend (Next.js) / Admin panel
        ↓
Backend API (:5554)
  creates session + interview context + definition
        ↓
LiveKit room
  metadata: session_id, context_id, definition_id
        ↓
Voice worker (aaptor)
  joins
        ↓
STT (Sarvam today)
        ↓
InterviewFlow / policy
        ↓
LLM
        ↓
validator
        ↓
TTS (ElevenLabs)
        ↓
Turns persisted to backend / brain
```

### Hard rule

**Policy decides section / stay-or-advance. LLM invents spoken question text. Policy must not write canned mid-interview questions.**

---

## Key directories

| Path | Owns |
|---|---|
| `services/voice-agent/products/interviewer/` | Aaptor live interview logic |
| `services/voice-agent/clients/` | STT / LLM / TTS providers |
| `services/voice-agent/livekit_adapters.py` | LiveKit STT/LLM/TTS plugins |
| `services/voice-agent/voice_platform/` | Shared AgentSession helpers |
| `services/backend-api/` | Sessions, contexts, admin definitions, scoring/brain |
| `apps/voice-frontend/` | Admin + candidate UI |
| `docs/` | Architecture / interviewer SOS / question-generation context |
| `document/rules/project-conventions.mdc` | Do-not-regress conventions |

---

## Interviewer core files

| File | Job |
|---|---|
| `worker.py` | LiveKit entrypoint: load context/definition, build outline, start session |
| `agent.py` | LiveKit AaptorAgent: `on_enter` opening, `llm_node` turns |
| `flow.py` | InterviewFlow state, prompts, generate/validate questions |
| `policy.py` | Agenda/clock: outline + `decide_next_action` |
| `prompts.py` | `UNIVERSAL_SYSTEM_V2`, `TURN_INSTRUCTIONS_V2`, opening instructions |
| `validator.py` | Question safety / grounding / parrot-block |
| `evidence.py` | Evidence ledger slots |
| `brain_runtime.py` | Checkpoint bridge to backend brain |

---

# Current interview behavior — competency-first

## Locked product rules

1. **Opening**
   - Approximately 1 minute.
   - At most one short resume project.
   - Then move toward the first admin competency.

2. **Warmup**
   - Jump to the first admin competency after approximately **3 minutes** or **5 interviewer turns**.
   - Controlled by `WARMUP_MAX_*` in `policy.py`.

3. **Competency questions**
   - Questions are standalone from the current JD/admin competency.
   - Examples: DSA, Python, ML, SQL, or whatever competencies are listed.
   - Do **not** hang competency questions on resume projects.

4. **Resume usage**
   - Resume excerpts/claims are allowed only on opening / `resume_project` turns.
   - Do not feed resume content into competency turns.

5. **Failed question generation**
   - If an LLM-generated question fails after one repair:
     - Soft-advance.
     - Use wording such as: “Let’s move on — …”
   - Never return canned STAR probes or `FALLBACK_PROBE_ROTATION`.

6. **Opening latency**
   - Opening must not leave the room silent.
   - Speak the first LLM chunk or fall back within approximately **6 seconds**.
   - Controlled by `OPENING_LLM_TIMEOUT_SECONDS` in `agent.py`.

7. **Prompt context**
   - The LLM receives:
     - JD
     - Resume, when allowed
     - Admin structure
     - Current competency
   - Relevant prompt paths:
     - `OPENING_INSTRUCTIONS_V2`
     - `TURN_INSTRUCTIONS_V2`
     - `_structured_system_prompt()` in `flow.py`

---

# Runtime commands — Windows

## Backend

```powershell
cd services\backend-api
python -m uvicorn main:app --host 0.0.0.0 --port 5554
```

## Voice worker

The worker must show:

```text
registered worker
agent_name: aaptor
```

Run:

```powershell
cd services\voice-agent
python aaptor_agent.py start
```

### Environment

Environment file:

```text
services/voice-agent/.env
```

The file is gitignored.

Typical providers:

```env
STT_PROVIDER=sarvam
SARVAM_API_KEY=...
STT_API_KEY=...

TTS_PROVIDER=elevenlabs
ELEVENLABS_API_KEY=...

LLM_SERVICE_URL=...
```

`LLM_SERVICE_URL` is OpenAI-compatible and may point to Ollama or a hosted service.

---

# Testing

After changes to flow, policy, prompts, validator, or interviewer behavior:

```powershell
cd services\voice-agent
python -m pytest -q --ignore=tests/live
```

Recently observed:

```text
276 passed, 2 skipped
```

After any prompt/policy/voice change:

1. Restart the voice worker.
2. Start a **new interview**.
3. Verify the runtime logs and actual voice behavior.

---

# Known failure modes

| Symptom | Likely cause |
|---|---|
| Interview silent at start | LLM opening stream slow; TTS failure; worker not registered; opening waited for full stream |
| Stuck on projects / never hits admin competencies | Warmup not advancing; outline missing competency IDs; definition not loaded |
| Robotic “Regarding X, tell me more…” | Bad STT + parrot phrasing; blocked as `generic_parrot_question` |
| Voice changed mid-call | ElevenLabs 401/402; resilient TTS failover to free voice |
| Worker dead / API down | Both may have been stopped manually; restart both |

### Opening silence mitigation

The opening flow has a timeout/fallback in `agent.py` to prevent the room from remaining silent.

---

# Useful log events

Look for these events when debugging:

```text
interviewer_on_enter_start
opening_llm_timeout
interviewer_speaking_opening
registered worker
interview_definition_loaded
phase_advanced
llm_question_output_rejected
```

---

# Do / Don't for agents

## Do

- Keep `policy.py` thin: **agenda + clock only**.
- Keep the **LLM as the speaker of questions**.
- Prefer editing:
  ```text
  services/voice-agent/products/interviewer/*
  ```
  rather than root wrappers.
- Run interviewer unit tests after changes to:
  - `flow.py`
  - `policy.py`
  - `prompts.py`
  - `validator.py`
- Treat API keys and secrets as sensitive.
- Never commit `.env` files or secrets.

## Don't

- Reintroduce canned probe banks as spoken mid-interview output.
- Feed resume content into competency turns.
- Force every competency into DSA.
- Use old LiveKit `VoicePipelineAgent` APIs except where compatibility aliases are explicitly required.
- Commit changes unless the user explicitly asks.

---

# Useful documentation

| File | Purpose |
|---|---|
| `README.md` | Topology + start commands |
| `docs/ai_interviewer_question_generation_context.md` | What feeds each question |
| `docs/interviewer_sos.md` | Production boundaries |
| `document/rules/project-conventions.mdc` | Verified facts / non-regressions |

---

# Agent handoff checklist

Before modifying the interviewer:

- [ ] Read `document/rules/project-conventions.mdc`.
- [ ] Check the current `flow.py`, `policy.py`, `prompts.py`, `validator.py`, and `agent.py`.
- [ ] Confirm the change does not move question generation into policy.
- [ ] Confirm competency turns do not consume resume context unless explicitly allowed.
- [ ] Run:
  ```powershell
  python -m pytest -q --ignore=tests/live
  ```
- [ ] Restart the worker.
- [ ] Start a fresh interview.
- [ ] Inspect relevant runtime log events.
- [ ] Verify actual spoken behavior, not just unit-test output.

> **Core invariant:** The policy controls *where the interview goes*; the LLM controls *what the interviewer says*.
