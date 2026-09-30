---
kind: business_term
name: Business Glossary
category: business_term
scope:
    - '**'
---

### Brain
- Definition：The interview state engine inside `services/backend-api/brain/` that compiles a question plan from the job description and candidate resume, drives live question generation during the interview, and produces structured scoring evidence. It persists compiled plans and live state to both Mongo and Redis.
- Aliases：interview brain、brain state

### Aaptor
- Definition：Internal codename for the AI Interviewer product line. The voice-agent hosts Aaptor prompts, interview state, planning integration, and its LiveKit worker under `products/interviewer/`. The root `aaptor_agent.py` is a compatibility entrypoint that registers the worker with `agent_name: aaptor`.
- Aliases：AI Interviewer、aaptor_agent

### Racko
- Definition：Internal codename for the Customer Support product line. Owns intent detection, tool use, retrieval, escalation logic, and its LiveKit worker under `products/customer_support/`. Root entrypoint `racko_agent.py` mirrors `aaptor_agent.py`.
- Aliases：customer support agent、racko_agent

### Phase 0
- Definition：Current development stage of the platform: Stage 1 plan endpoint, Stage 2 live question generation via `AgentSession`, retry-wrapped HTTP clients, `/health` + `/health/all`, and an integrated Next.js demo supporting both Aaptor and Racko products. Not yet a production candidate portal.

### Laptop topology
- Definition：Pilot deployment model where each of four laptops runs one component (LLM/Ollama, STT/Nemotron, TTS/Kokoro+Redis, backend-api+voice-agent+Mongo) communicating over LAN via HTTP. Designed to migrate to real GPU servers with zero code changes by swapping URLs only.
- Aliases：4-laptop pilot、laptop assignment

### Interview session
- Definition：A single candidate interview lifecycle managed by the backend-api: creation, invitation token issuance, LiveKit room join, brain-driven question flow, live transcript capture, and scorecard generation. Sessions are identified by UUIDs and tracked across Mongo, Redis brain state, and LiveKit room state.
- Aliases：session、candidate session

### Scorecard
- Definition：Structured evaluation output produced by the brain's scoring pipeline against predefined evidence dimensions. Persisted per interview and queryable via admin routes; includes dimension scores and raw evidence extracted from the transcript.
- Aliases：evaluation、score

### Candidate journey
- Definition：End-to-end flow a candidate experiences: landing page → device pre-check → LiveKit room join → AI interviewer conversation → results screen. Implemented in `apps/voice-frontend/components/CandidateInterviewJourney.tsx` and consumed by the invite-based candidate route.
- Aliases：candidate flow、interview journey

### Recruiter setup
- Definition：Admin-facing UI flow for recruiters to configure an interview template (job description, candidate resume, scoring rubric) and generate an invite link. Implemented in `apps/voice-frontend/components/RecruiterInterviewSetup.tsx` and `SetupForm.tsx`.
- Aliases：template setup、recruiter flow

### Voice policy
- Definition：TTS provider selection and routing configuration in `services/voice-agent/clients/tts/voice_policy.py`. Determines which TTS backend (Kokoro, Deepgram, etc.) handles synthesis for a given request, including cross-provider sanitization and default voice selection.
- Aliases：tts policy、voice_policy
