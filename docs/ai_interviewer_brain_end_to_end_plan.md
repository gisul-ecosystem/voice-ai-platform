# AI Interviewer Brain — End-to-End Architecture and Delivery Plan

## 1. Purpose

Build a domain-neutral interview brain that can conduct structured, natural interviews for technical and non-technical roles while retaining enough control for consistency, evidence-based scoring, recovery, and human review.

The system must understand:

- What the job requires.
- What the candidate claims in the resume.
- What the candidate confirms during the conversation.
- What has already been asked.
- Which answer belongs to which question.
- What evidence has been collected for each competency.
- What information is still missing.
- What level of depth is appropriate.
- When to clarify, continue, change topic, or close.

The design must not depend on hardcoded technical topics in the universal system prompt.

---

## 1A. Implementation status (as of 2026-09-18)

This section is the source of truth for **what is built now** versus what remains planned.

### Built and wired end-to-end

| Area | Status | Notes |
|------|--------|-------|
| Milestone 0 schemas / defaults / publish rules | Done | `models/brain.py`, `brain/defaults.py`, `brain/publish.py` |
| JD / resume text intelligence | Done | Heuristic extractors with provenance |
| PDF / DOCX / TXT ingest | Done | Text-layer extract via `pypdf` / `python-docx` (no OCR yet) |
| Blueprint compiler + publish | Done | Competencies, ladders, probes, time policy |
| Immutable definition persistence | Done | Mongo `interview_definitions`; attached on schedule |
| 3-layer live memory | Done | Worker RAM → Redis hot snapshot → Mongo durable |
| Policy-driven live interview | Done | Breadth-first; depth/probe/time caps enforced |
| Full transcript persistence | Done | All agent/candidate/clarify turns in `interview_turns` |
| Advisory scorecard | Done | Evidence-linked; auto on `completed`; human review required |

### Not done yet

| Area | Status |
|------|--------|
| OCR for scanned / image-only PDFs | Pending |
| Full creator blueprint editor UI | Partial (SetupForm ingest fills fields; `/jd/approve` and `/resume/confirm` exist but are not the primary UI path) |
| Milestone 5 voice pin / TTS preflight / no silent voice switch | Pending |
| Scorecard review / override APIs + recruiter UI | Pending (schema fields + `human_review_status=pending` only; GET/generate exist) |
| Formal M7 role/failure validation matrix | Pending |

### Level vs experience (decided behaviour)

1. **Target job level** (creator seniority) sets rubric bar, max depth, and required intents.
2. **Candidate experience** (resume profile) adapts question framing/examples only.
3. **Demonstrated depth** (live answers) controls progressive probing.
4. The job bar is **never silently lowered** because the candidate is a student or junior.

---

## 2. Product principles

1. **Job requirements define the assessment.**  
   Resume content personalizes the interview but does not silently change the scoring standard.

2. **Standardize assessment intent, not exact wording.**  
   Candidates for the same role are assessed against the same competencies, evidence expectations, and scoring anchors. Question wording may adapt to experience and prior answers.

3. **Breadth before depth.**  
   The interviewer establishes the candidate's background and relevant evidence before selecting a topic for deeper probing.

4. **The policy engine controls progression.**  
   The LLM phrases questions naturally but does not independently decide the entire interview flow.

5. **Resume claims are not verified evidence.**  
   Claims become evidence only after the candidate explains or demonstrates them.

6. **Scoring must cite evidence.**  
   Every score must link to transcript turns. Missing evidence produces `not_assessed`, not an invented low score.

7. **The AI is advisory.**  
   Final hiring decisions remain under human responsibility.

8. **No voice-based personality or emotion scoring.**  
   Accent, pitch, speaking speed, inferred emotion, appearance, age, gender, disability, family status, religion, and similar characteristics are excluded.

9. **A published interview definition is immutable.**  
   Changes create a new version so every candidate can be audited against the exact configuration used.

10. **Failures must be explicit and recoverable.**  
    Context, persistence, STT, LLM, TTS, and network failures must not silently change interview behaviour.

---

## 3. Current architecture (as built)

```text
Creator / Demo UI (apps/voice-frontend)
          |
          | BFF service token
          v
Next.js API routes (/api/brain/ingest, /api/interviews, /api/sessions/...)
          |
          v
backend-api (FastAPI)
  +----------------------------------------------+
  | Document ingest (PDF/DOCX/TXT text-layer)    |
  | JD + resume extractors                       |
  | Blueprint compiler + publish validation      |
  | Immutable interview definitions (Mongo)      |
  | Schedule + invitation + context              |
  | Session lifecycle + turn transcript          |
  | 3-layer brain store (RAM/Redis/Mongo)        |
  | Scorecard generation on completed            |
  +----------------------------------------------+
          |
          | worker service token + context_id / definition_id
          v
voice-agent interviewer worker (LiveKit)
  +----------------------------------------------+
  | Load published definition                    |
  | Policy engine (next action / depth / close)  |
  | InterviewFlow question phrasing (LLM)         |
  | BrainSessionBridge (Q/A + checkpoints)       |
  | Persist every spoken turn                    |
  +----------------------------------------------+
          |
          v
MongoDB durable records
  interview_contexts
  interview_definitions
  interview_sessions
  interview_turns          <-- full transcript
  interview_questions
  interview_answers
  interview_evidence
  interview_brain_snapshots
  interview_scorecards
          ^
          |
Redis (optional hot layer)
  interview:brain:{session_id}
```

### Runtime interview flow

```text
Schedule interview
  -> auto-compile/publish definition (or reuse definition_id)
  -> store context + definition_id
  -> candidate joins via invitation
  -> session created (definition_id copied from context)
  -> worker loads definition + enables policy mode
  -> opening -> candidate map -> baseline -> competency cycles -> close
  -> every spoken turn stored
  -> status=completed triggers advisory scorecard
  -> human review required before hiring use
```

### Deployment boundary

Do not introduce a separate context-engine microservice for Aaptor interviewer.

- `apps/voice-frontend`: creator/candidate demo UX + BFF proxies.
- `services/backend-api`: document intelligence, blueprint compilation, durable state, scoring, APIs.
- `services/voice-agent`: live interview orchestration, policy execution, voice interaction.
- MongoDB: durable source of truth.
- Redis: hot brain snapshots (memory fallback if unset).
- LiveKit: real-time media transport.
- Provider adapters: STT, LLM, and TTS.

A separate service should be considered only after measured scaling, ownership, or deployment requirements justify it.

### Key code map

| Concern | Location |
|---------|----------|
| Schemas | `services/backend-api/models/brain.py` |
| Extract / ingest | `brain/extractors.py`, `brain/documents.py` |
| Compile / publish | `brain/compiler.py`, `brain/publish.py`, `brain/definition_service.py` |
| 3-layer state | `brain/state_store.py`, `db/redis_brain.py`, `db/brain.py` |
| Scoring | `brain/scoring.py`, `brain/scoring_service.py`, `db/scorecards.py` |
| Policy runtime | `services/voice-agent/products/interviewer/policy.py` |
| Live flow | `products/interviewer/flow.py`, `agent.py`, `worker.py`, `brain_runtime.py` |

### API surface (as built)

| Surface | Auth | Routes |
|---------|------|--------|
| Intelligence | BFF service token | `POST /interview-brain/documents/ingest`, `/jd/extract`, `/jd/approve`, `/resume/extract`, `/resume/confirm`, `/compile`, `/publish` |
| Definitions | Worker / BFF | `GET /interview-brain/definitions/{definition_id}` |
| Brain state | Worker service token | `GET/PUT /internal/interview-sessions/{id}/brain`, `POST …/brain/questions\|answers\|evidence` |
| Transcript | Worker write / BFF read | `POST /internal/interview-sessions/{id}/turns`, `GET …/transcript` |
| Scorecard | BFF / internal | `GET …/scorecard`, `POST …/scorecard/generate` (auto on `completed`) |
| Schedule | BFF | `/v1/...` scheduled interviews; auto `publish_and_store` attaches `definition_id` |

### Operational notes (as built)

- Redis key: `interview:brain:{session_id}`; env `REDIS_URL`, `INTERVIEW_BRAIN_REDIS_TTL_SECONDS` (default 21600). Unset Redis → process-local hot store.
- Document ingest caps: 2MB upload; text-layer PDF/DOCX/TXT/MD; encrypted/blank PDFs rejected (OCR not implemented).
- Schedule path auto-approves JD intelligence before compile when publishing a definition for a new interview.
- Definitions and AI scorecards are insert-only (no overwrite of published versions / first AI card).
- Missing `definition_id` → worker falls back to legacy outline flow (policy mode off).
- Frontend BFF today: ingest + session transcript/scorecard proxies. Extract/approve/compile are backend-direct or schedule-driven.

---

## 3A. Target architecture (long-term product shape)

The longer-term product shape remains:

```text
Interview Creator Portal
          |
          v
Next.js Backend-for-Frontend
          |
          v
Interview Configuration API
          |
          +--> JD Intelligence
          +--> Resume Intelligence
          +--> Occupation/Skill Normalization
          +--> Blueprint Compiler
          +--> Validation and Versioning
          |
          v
Creator Review and Publish
          |
          v
Immutable Interview Definition
          |
          v
Schedule + Signed Invitation
          |
          v
LiveKit Candidate Session
          |
          v
Interview Runtime
  +-------------------------------+
  | Durable Memory                |
  | Coverage and Evidence Tracker |
  | Next-Action Policy            |
  | Time and Ending Controller    |
  | Question Generator            |
  | Question Validator            |
  +-------------------------------+
          |
          v
Transcript + Evidence + Final State
          |
          v
Asynchronous Scorecard
          |
          v
Recruiter Review and Decision
```

## 4. Domain-neutral prompt architecture

### 4.1 Stable universal system prompt

The system prompt defines how the interviewer behaves:

```text
You are a professional structured interviewer.

Conduct a fair, job-related interview using the supplied interview
definition and next action.

Rules:
- Ask one clear question at a time.
- Follow the supplied competency, objective, and allowed depth.
- Use candidate facts only when supported by the supplied sources.
- Do not repeat an answered question.
- Do not invent candidate, organisation, project, or job information.
- Do not ask about protected personal characteristics.
- Do not reveal scores or make hiring decisions.
- Do not include multiple unrelated questions.
- Speak professionally, naturally, and concisely.
- Return only the required structured response.
```

The permanent prompt must not contain role-specific topics such as APIs, databases, sales objections, patient care, accounting, or logistics.

### 4.2 Dynamic interview definition

The approved definition supplies:

- Role and target level.
- Competencies.
- Required evidence.
- Rubrics.
- Core assessment intents.
- Allowed probes.
- Approved scenarios.
- Time and completion policies.

### 4.3 Runtime context

Each request supplies only relevant state:

```json
{
  "current_competency": {},
  "candidate_profile_summary": {},
  "next_action": "probe_for_personal_action",
  "last_answer": "...",
  "relevant_evidence": [],
  "missing_evidence": [],
  "recent_questions": [],
  "prohibited_repetitions": [],
  "remaining_seconds": 840
}
```

### 4.4 Structured generation result

```json
{
  "question": "What part of that work did you personally complete?",
  "competency_id": "problem_solving",
  "intent": "establish_ownership",
  "depth": 2,
  "source_claim_ids": ["claim_18"]
}
```

The output is validated before it is persisted and spoken.

---

## 5. Interview creator flow

### Step 1: Interview identity

Mandatory:

- Interview title.
- Role title.
- Target seniority.
- Duration.
- Interview language.
- Timezone.

Optional:

- Department.
- Domain.
- External job/ATS ID.
- Internal tags.
- Hiring manager.

### Step 2: Job description and role understanding

The creator provides the JD or structured role requirements.

The system extracts:

- Responsibilities and tasks.
- Mandatory and preferred requirements.
- Required entry-level competencies.
- Experience expectations.
- Education requirements when job-related.
- Knowledge and skills.
- Tools or systems.
- Expected outcomes.
- Typical work scenarios.
- Regulatory, safety, or compliance requirements.

Each extracted item stores:

- Original source span.
- Explicit or inferred classification.
- Confidence.
- Creator confirmation.

Occupation taxonomies such as O*NET or ESCO may normalize terminology and suggest missing competencies, but they do not override the creator.

### Step 3: Competencies and objectives

The system recommends approximately four to six interviewable competencies for a normal interview.

For each competency:

- Definition.
- Job relevance.
- Required proficiency.
- Evidence expectations.
- Minimum assessment intent.
- Allowed depth.
- Scoring anchors.

Optional objective weights may be configured. If absent, use equal weighting.

### Step 4: Questions, probes, and scenarios

Support:

- Creator-provided questions.
- Reusable approved question-bank items.
- AI-generated questions from approved job requirements.
- Creator-provided scenarios.
- AI-generated scenarios validated against the JD.

The creator approves the blueprint as a whole by publishing it. A separate approver is not required for every interview. Reusable organisation templates can be approved once.

### Step 5: Candidate and resume

Scheduling requires:

- Candidate identifier/name.
- Candidate contact destination.
- Scheduled date and time.
- Invitation policy.

The resume may be mandatory or optional according to the published template.

### Step 6: Runtime policies

Configure or accept safe defaults for:

- Adaptive follow-ups.
- Maximum depth.
- Non-answer handling.
- Clarification attempts.
- Time-overrun grace.
- Candidate final-addition opportunity.
- Recording and monitoring.
- Ending behaviour.
- TTS voice policy.

### Step 7: Scoring policy

Configure:

- Scoring enabled/disabled.
- Competency weights.
- Minimum evidence.
- Human review.
- Recommendation visibility.
- Override requirements.

### Step 8: Review and publish

Display:

- Parsed role requirements.
- Competencies.
- Evidence expectations.
- Question ladders.
- Scenarios.
- Rubrics.
- Timing.
- Runtime policies.
- Candidate experience.
- Expected scorecard shape.

Publishing is blocked if:

- Role or target level is missing.
- No JD/structured role requirements are approved.
- No mandatory competency exists.
- A competency has no evidence expectations or rubric.
- The time plan is invalid.
- Objective weights are invalid.
- A prohibited question is detected.
- High-risk extraction conflicts remain unresolved.

Fixed question wording, fixed project count, scenarios, weights, and resume are not universally mandatory.

---

## 6. JD intelligence

### 6.1 Data contract

```json
{
  "role": {
    "title": "Backend Engineer",
    "occupation_code": null,
    "domain": "Financial services",
    "target_level": "junior"
  },
  "responsibilities": [],
  "mandatory_requirements": [],
  "preferred_requirements": [],
  "knowledge": [],
  "skills": [],
  "competencies": [],
  "tools": [],
  "work_scenarios": [],
  "expected_outcomes": [],
  "source_references": [],
  "extraction_version": "jd-extractor-v1"
}
```

### 6.2 Processing pipeline

```text
Raw JD
  -> Text normalization
  -> Structured extraction
  -> Requirement classification
  -> Skill/occupation normalization
  -> Duplicate and contradiction checks
  -> Schema validation
  -> Creator review
  -> Approved job intelligence
```

### 6.3 Rules

- Separate mandatory from preferred requirements.
- Separate job duties from company marketing text.
- Do not create competencies from vague cultural language.
- Identify competencies that can realistically be assessed in an interview.
- Preserve source provenance.
- Require human correction for low-confidence or contradictory items.

---

## 7. Resume intelligence

### 7.1 Processing pipeline

```text
PDF/DOCX upload
  -> Malware and size validation
  -> Layout-aware text extraction
  -> OCR fallback for scanned pages
  -> Section detection
  -> Structured extraction
  -> Date normalization
  -> Overlap-aware experience calculation
  -> Source-span verification
  -> Schema validation
  -> Creator-visible review
```

### 7.2 Candidate profile

```json
{
  "education": [],
  "professional_experience": [],
  "internships": [],
  "projects": [],
  "skills_claimed": [],
  "certifications": [],
  "achievements": [],
  "languages": [],
  "experience_summary": {
    "professional_months": 0,
    "internship_months": 6,
    "profile_type": "final_year_student"
  },
  "claims": [],
  "extraction_version": "resume-extractor-v1"
}
```

Every claim includes:

```json
{
  "claim_id": "claim_18",
  "type": "project",
  "value": "Built an inventory management application",
  "source": "resume",
  "source_span": "Developed an inventory management...",
  "page": 2,
  "confidence": 0.94,
  "confirmed": false
}
```

### 7.3 Rules

- Do not infer proficiency percentages.
- Do not count overlapping dates twice.
- Separate academic, personal, internship, and professional projects.
- Distinguish team results from claimed personal contribution.
- Mark missing or ambiguous dates.
- Treat listed technologies and skills as unverified claims.
- Exclude protected or irrelevant personal information from question generation and scoring.
- Allow facts stated during the interview to be recorded separately as `candidate_statement`.

---

## 8. Candidate level and difficulty

Maintain three different concepts:

1. **Target job level** — selected by the creator and used by the rubric.
2. **Candidate profile** — education and experience extracted from evidence.
3. **Demonstrated depth** — observed during the interview.

The target job level must not be silently lowered because a candidate is a student or has a particular degree.

### Experience-aware framing

- Student/final year: academic projects, internships, applied fundamentals, reflection.
- Junior: implementation, debugging, testing, basic trade-offs.
- Mid-level: ownership, production situations, reliability, collaboration.
- Senior: architecture, scale, risk, leadership, strategic trade-offs.

### BCA and MCA candidates for the same role

Use:

- The same competencies.
- The same evidence expectations.
- The same scoring anchors.
- Adapted wording based on available experience.

Do not use the degree as a proxy for ability.

---

## 9. Interview blueprint

### 9.1 Definition

```json
{
  "definition_id": "idef_123",
  "version": 3,
  "role": {},
  "competencies": [],
  "assessment_intents": [],
  "question_ladders": [],
  "allowed_probes": [],
  "scenario_bank": [],
  "rubrics": [],
  "time_policy": {},
  "non_answer_policy": {},
  "ending_policy": {},
  "voice_policy": {},
  "prompt_version": "interviewer-system-v2",
  "published_at": "...",
  "published_by": "creator_123"
}
```

### 9.2 Standardize

- Competency definitions.
- Evidence expectations.
- Scoring anchors.
- Mandatory assessment intents.
- Allowed probing range.
- Time and ending policies.
- Safety and prohibited-content rules.

### 9.3 Adapt

- Exact question wording.
- Candidate examples.
- Resume/project references.
- Depth reached.
- Number of clarifications.
- Project selection.
- Approved scenario selection.

---

## 10. Human-like interview choreography

### 10.1 Thirty-minute default

#### Minute 0–2: Opening

- Greet the candidate.
- Confirm readiness.
- Explain the high-level structure.
- Confirm the role.
- Invite a concise introduction.

#### Minute 2–5: Candidate map

- Confirm current education/employment status.
- Ask which experience or project is most relevant.
- Establish broad ownership and context.
- Do not immediately begin an advanced deep-dive.

#### Minute 5–9: Baseline assessment

- Ask an applied baseline question for the first mandatory competency.
- Determine whether the candidate can explain context and personal contribution.

#### Minute 9–22: Competency cycles

- Cover the highest-priority mandatory competencies.
- Use controlled progressive depth.
- Stop probing when evidence is sufficient.
- Move forward when further depth has low assessment value.

#### Minute 22–26: Scenario or work sample

- Select an approved scenario when enabled.
- Assess application, reasoning, and decision process.

#### Minute 26–28: Coverage check

- Identify one important missing evidence area.
- Ask at most one short gap-closing question.

#### Minute 28–30: Closing

- Let the current answer finish.
- Give the candidate an opportunity to add one relevant point.
- Explain next steps.
- Thank the candidate.
- Persist completion state.

### 10.2 Time boundaries

For a 30-minute interview:

- Soft boundary: 26–27 minutes.
- Target end: 30 minutes.
- Expected completion: by 33 minutes.
- Hard maximum: 35 minutes.

Never cut off an active candidate response at the target timestamp.

---

## 11. Progressive question ladder

Each competency uses a controlled ladder:

```text
Depth 1: Establish context
Depth 2: Establish personal ownership
Depth 3: Understand application or execution
Depth 4: Examine problem, failure, or complexity
Depth 5: Examine trade-off, improvement, or transfer
```

Rules:

- Begin at a depth appropriate to the target level and candidate context.
- Do not jump multiple levels without evidence.
- Clarify unclear answers at the same level.
- Advance one level when the current answer is sufficient.
- Skip unnecessary probes after a strong answer.
- Move to the next competency when required evidence is covered.
- Enforce maximum depth and probe count from the blueprint.

For technical roles, avoid pure trivia unless factual recall is explicitly job-critical. Prefer applied questions connected to work, projects, debugging, design, validation, or trade-offs.

---

## 12. Project selection and coverage

Do not require a fixed number of projects and do not deeply cover every resume project.

### 12.1 Project ranking

Rank projects by:

- Relevance to the JD.
- Candidate ownership.
- Recency.
- Appropriate complexity.
- Opportunity to collect missing competency evidence.
- Extraction confidence.

### 12.2 Interview use

```text
Brief project inventory
  -> Select most relevant project
  -> Establish context and ownership
  -> Ask one applied decision question
  -> Ask one problem/outcome question if needed
  -> Move forward when evidence is sufficient
  -> Use another project only to fill a competency gap
```

Competency coverage, not project count, is the standard.

---

## 13. Durable interview memory

### 13.1 Runtime state

```json
{
  "session_id": "ses_123",
  "state_version": 19,
  "definition_id": "idef_123",
  "current_section": "competency_assessment",
  "current_competency_id": "problem_solving",
  "current_depth": 3,
  "active_question_id": "q_14",
  "asked_question_ids": [],
  "candidate_claim_ids": [],
  "coverage": {},
  "consecutive_unusable_answers": 0,
  "elapsed_seconds": 940,
  "last_processed_turn_id": "turn_31"
}
```

### 13.2 Question ledger

```json
{
  "question_id": "q_14",
  "session_id": "ses_123",
  "competency_id": "problem_solving",
  "intent": "probe_for_result",
  "depth": 3,
  "text": "What result did you observe after making that change?",
  "source_claim_ids": ["claim_18"],
  "status": "spoken",
  "asked_at": "..."
}
```

Question statuses:

- `planned`
- `spoken`
- `interrupted`
- `answered`
- `skipped`

### 13.3 Answer linkage

```json
{
  "answer_id": "answer_14",
  "question_id": "q_14",
  "turn_ids": ["turn_31", "turn_32"],
  "status": "answered",
  "usable": true,
  "final_transcript": "...",
  "completed_at": "..."
}
```

### 13.4 Evidence

```json
{
  "evidence_id": "ev_21",
  "session_id": "ses_123",
  "competency_id": "problem_solving",
  "question_id": "q_14",
  "turn_ids": ["turn_31"],
  "claim": "Identified the cause using logs and reproduced the issue",
  "strength": "sufficient",
  "missing_details": ["measured outcome"],
  "confidence": 0.84
}
```

### 13.5 Coverage

```json
{
  "problem_solving": {
    "status": "partial",
    "required_intents": ["problem", "action", "reasoning", "result"],
    "covered_intents": ["problem", "action", "reasoning"],
    "missing_intents": ["result"],
    "evidence_ids": ["ev_18", "ev_21"]
  }
}
```

### 13.6 Persistence rules

- Persist final transcripts idempotently.
- Link every usable answer to an active question.
- Persist the question before speech begins.
- Save a snapshot after each processed final answer.
- Use optimistic concurrency on `state_version`.
- Restore exact state after worker restart.
- Do not reconstruct probe count by merely counting transcript turns.

---

## 14. Next-action policy engine

Allowed actions:

```text
OPEN_INTERVIEW
MAP_CANDIDATE_BACKGROUND
ASK_BASELINE
CLARIFY_CURRENT_ANSWER
PROBE_FOR_CONTEXT
PROBE_FOR_OWNERSHIP
PROBE_FOR_METHOD
PROBE_FOR_REASONING
PROBE_FOR_RESULT
PROBE_FOR_REFLECTION
INCREASE_DEPTH
MOVE_TO_NEXT_COMPETENCY
ASK_APPROVED_SCENARIO
CHECK_REMAINING_GAP
OFFER_FINAL_ADDITION
CLOSE_INTERVIEW
PAUSE_FOR_SERVICE_RECOVERY
```

Priority order:

1. Safety, service recovery, and explicit candidate requests.
2. Active unanswered question.
3. Time boundary.
4. Mandatory competency coverage.
5. Evidence gap in current competency.
6. Approved scenario.
7. Closing.

The policy returns a structured decision with a reason. The LLM cannot override prohibited actions, maximum depth, time limits, or completed coverage.

---

## 15. Answer usability and non-answer policy

Classify each candidate response as:

- `usable`
- `needs_clarification`
- `too_short`
- `off_topic`
- `explicit_unknown`
- `silence`
- `stt_failure`
- `network_failure`
- `candidate_requested_repeat`

Default progression:

```text
First unusable answer
  -> Clarify

Second consecutive unusable answer
  -> Rephrase more simply

Third consecutive unusable answer
  -> Change approach/competency and check for difficulty

Fourth consecutive unusable answer
  -> Ask whether the candidate can and wants to continue

Confirmed inability or unwillingness
  -> Close professionally with insufficient evidence
```

Rules:

- Reset the counter after a usable answer.
- Incorrect but relevant answers remain usable assessment evidence.
- STT and network failures do not count.
- Clarification requests do not count.
- Never automatically label the candidate as failed.

---

## 16. Real-time evidence and final scoring

### 16.1 During the interview

Track evidence sufficiency:

- `none`
- `weak`
- `partial`
- `sufficient`
- `strong`
- `contradictory`

This controls follow-up selection. It is not the final hiring score.

### 16.2 After the interview

For each competency:

```json
{
  "competency_id": "problem_solving",
  "rating": 3,
  "anchor": "Explains a relevant problem, action, reasoning, and result",
  "evidence_ids": ["ev_18", "ev_21"],
  "contradictory_evidence_ids": [],
  "missing_evidence": [],
  "confidence": 0.78,
  "review_required": true
}
```

Possible outcomes:

- Numeric anchored score.
- `not_assessed`.
- `insufficient_evidence`.
- `review_required`.

Do not average per-turn quality scores. Evaluate the complete evidence set against the competency rubric.

### 16.3 Human review

- Human review is mandatory initially.
- Recruiters see source transcript excerpts.
- Overrides require a reason.
- Preserve AI and human versions.
- Never announce scores during the candidate session.

---

## 17. Ending controller

Normal closing:

1. Acknowledge the final answer.
2. Confirm that the structured portion is complete.
3. Offer one opportunity to add relevant information.
4. Explain that the hiring team will review the interview.
5. Thank the candidate.
6. Persist `completing`.
7. Deliver closing speech.
8. Persist `completed`.
9. Disconnect.

Early closing:

- Confirm the candidate's intent.
- Distinguish candidate choice from service failure.
- Store a non-judgmental completion reason.
- Use `insufficient_evidence` when assessment could not be completed.

---

## 18. TTS voice consistency

Pin this configuration at session creation:

```json
{
  "provider": "elevenlabs",
  "voice_id": "approved-voice-id",
  "model_id": "approved-model-id",
  "stability": 0.7,
  "speed": 0.9,
  "fallback_policy": "same_voice_retry_then_pause"
}
```

Required behaviour:

- Preflight the provider and voice before admission.
- Retry the same voice for transient failures.
- Do not silently choose another voice ID.
- Do not silently switch TTS providers.
- Pause with a neutral recovery message when possible.
- End gracefully with a service reason if recovery fails.
- Emit operational alerts without logging candidate content or credentials.

---

## 19. Data model

Recommended collections:

```text
interview_templates
interview_definition_versions
job_intelligence
candidate_profiles
candidate_claims
scheduled_interviews
interview_sessions
interview_questions
interview_answers
interview_turns
interview_evidence
interview_state_snapshots
interview_scorecards
interview_review_events
```

Important indexes:

- Unique definition version per template.
- Unique question ID per session.
- Unique answer ID per session.
- Unique turn ID per session.
- Unique state version per session.
- Ordered turns by session and sequence.
- Evidence by session and competency.
- Retention TTL where legally and operationally appropriate.

---

## 20. API surface

> **As-built routes** are listed in §3 (“API surface (as built)”). This section remains the longer-term product-shaped API inventory.

### Templates and definitions

```text
POST /v1/interview-templates
GET  /v1/interview-templates/{id}
PUT  /v1/interview-templates/{id}

POST /v1/interview-templates/{id}/analyse-jd
PUT  /v1/interview-templates/{id}/job-intelligence
PUT  /v1/interview-templates/{id}/competencies
PUT  /v1/interview-templates/{id}/rubrics
PUT  /v1/interview-templates/{id}/policies
POST /v1/interview-templates/{id}/generate-blueprint
POST /v1/interview-templates/{id}/validate
POST /v1/interview-templates/{id}/publish
```

### Candidate profiles

```text
POST /v1/candidate-applications
POST /v1/candidate-applications/{id}/resume
POST /v1/candidate-applications/{id}/analyse-resume
PUT  /v1/candidate-applications/{id}/confirm-profile
```

### Runtime state

```text
GET  /v1/internal/sessions/{id}/brain-state
POST /v1/internal/sessions/{id}/questions
POST /v1/internal/sessions/{id}/answers
POST /v1/internal/sessions/{id}/evidence
PUT  /v1/internal/sessions/{id}/snapshot
POST /v1/internal/sessions/{id}/status
```

### Scorecards

```text
# As built:
GET  /internal/interview-sessions/{id}/scorecard
POST /internal/interview-sessions/{id}/scorecard/generate   # also auto on completed

# Target (not built):
POST /v1/internal/sessions/{id}/scorecard-jobs
POST /v1/sessions/{id}/scorecard/review
POST /v1/sessions/{id}/scorecard/override
```

All internal writes must be authenticated, idempotent, and correlation-ID aware.

---

## 21. Reliability and observability

### Storage layers (production scale)

```text
Layer 1: Worker RAM
  Live decision state for one session/job

Layer 2: Redis (`interview:brain:{session_id}`)
  Hot shared snapshot with TTL
  Multi-worker recovery

Layer 3: MongoDB
  interview_questions / interview_answers / interview_evidence
  interview_brain_snapshots (versioned)
  Durable audit and scoring source of truth
```

Session isolation is mandatory: every Redis key and Mongo document is scoped by `session_id`. Concurrent interviews never share brain state.

Track:

- JD/resume extraction latency and confidence.
- Blueprint generation failures.
- Context size and token usage.
- STT finalization latency.
- Question decision and generation latency.
- Question validation failures.
- Repeated-question rate.
- Evidence extraction failures.
- State-version conflicts.
- Recovery count.
- TTS provider/voice consistency.
- Interview duration and overrun.
- Completion and early-ending reasons.
- Scorecard latency and reviewer overrides.

Do not log:

- Raw API keys or tokens.
- Full resumes.
- Full transcripts.
- Candidate email or unnecessary PII.

Use opaque IDs and controlled, access-audited data stores.

---

## 22. Delivery roadmap

### Milestone 0: Product contract — DONE

Deliver:

- Final schemas.
- Default policies.
- Publication rules.
- Versioning rules.
- Privacy and retention boundaries.

Exit criteria:

- Backend Engineer and Sales Executive definitions can be represented without schema changes.

### Milestone 1: JD and resume intelligence — MOSTLY DONE

Deliver:

- Secure document ingestion. *(text PDF/DOCX/TXT done; OCR pending)*
- JD extractor.
- Resume extractor.
- Provenance and confidence.
- Experience calculation.
- Creator review APIs and UI. *(API + SetupForm review checkboxes; full editor pending)*

Exit criteria:

- Required fields are evaluated against a labelled test set. *(unit tests present; labelled set pending)*
- Hallucinated candidate facts fail validation.
- Scanned and text PDFs have tested behaviour. *(text done; scanned OCR pending)*

### Milestone 2: Blueprint compiler — DONE

Deliver:

- Competency suggestions.
- Assessment intents.
- Question ladders.
- Allowed probes.
- Scenario support.
- Behavioral anchors.
- Duration allocation.
- Publish validation and immutable versions.

Exit criteria:

- Technical and non-technical blueprints use the same generic system prompt.
- Every question intent maps to a competency and expected evidence.

### Milestone 3: Durable memory — DONE

Deliver:

- Question ledger.
- Answer linkage.
- Candidate-statement claims. *(schema ready; live claim extraction still thin)*
- Evidence records.
- Coverage matrix. *(schema + scoring coverage; live coverage tracker still evolving)*
- Versioned snapshots.
- Exact worker recovery.

Exit criteria:

- A worker can restart after any final answer and continue without repeating or losing state.

### Milestone 4: Policy-driven live interview — MOSTLY DONE

Deliver:

- Breadth-first opening.
- Progressive depth.
- Project ranking. *(basic resume project coverage remains; full ranking pending)*
- Deterministic next actions.
- Question validation. *(policy caps; richer validator pending)*
- Non-answer handling. *(usability + clarify path; full 4-step ladder pending)*
- Time controller.
- Structured closing.

Exit criteria:

- The LLM cannot exceed depth, time, probe, or prohibited-content policies.
- The interview does not immediately deep-dive without establishing context.

### Milestone 5: Voice reliability — PENDING

Deliver:

- Session-pinned voice configuration.
- TTS preflight.
- Same-voice retries.
- Pause/end recovery policy.
- Provider and voice observability.

Exit criteria:

- Automated failure tests never produce an unannounced voice change.

### Milestone 6: Scorecards — MOSTLY DONE

Deliver:

- Asynchronous evidence extraction verification. *(deterministic evidence builder done)*
- Anchored competency scoring.
- Confidence and insufficient-evidence handling.
- Recruiter review and overrides. *(schema + pending status only; review/override APIs and UI pending)*
- Complete audit trail. *(scorecard + evidence + transcript; review events pending)*

Exit criteria:

- Every numeric score has valid evidence references.
- Unsupported claims are rejected.
- Human and AI results remain separately auditable.

### Milestone 7: Production validation — PENDING

Validate:

- Junior Backend Engineer.
- Senior Backend Engineer.
- BCA final-year candidate.
- MCA final-year candidate.
- Sales Executive.
- Sparse resume.
- No professional experience.
- Repeated non-answers.
- Interrupted and reconnected sessions.
- TTS failure.
- Planning/scoring provider failure.

Measure:

- JD extraction accuracy.
- Resume field precision/recall.
- Hallucinated-fact rate.
- Mandatory competency coverage.
- Repeated-question rate.
- Depth progression correctness.
- Evidence citation validity.
- Human/AI scoring agreement.
- Question latency.
- Voice consistency.
- Duration compliance.

---

## 23. Migration from the current implementation

Most evolutionary steps are complete on the interviewer product path. Remaining work is reliability, UI polish, and formal validation.

| Step | Status |
|------|--------|
| Preserve LiveKit transport and provider clients | Done |
| Stable generic system prompt (domain-neutral) | Done |
| Versioned immutable interview definitions | Done |
| Structured resume claims (vs project-name matching) | Partial — claims schema exists; live claim extraction still thin |
| Question / answer / evidence / snapshot records | Done |
| Policy engine replaces LLM probe/advance control | Done |
| Full transcript + explicit Q/A linkage | Done |
| Feature-flag / shadow planner | Skipped — evolutionary cutover on interviewer product |
| Role / recovery / latency / evidence validation matrix | Pending (M7) |

---

## 24. Recommended default decisions

- Initial validation roles: Backend Engineer and Sales Executive.
- Creator publication counts as approval.
- Standardize competency intent and rubric, not exact question wording.
- Select projects based on evidence gaps, not a fixed count.
- Support creator-provided and AI-generated approved scenarios.
- Use four consecutive unusable responses as a confirmation threshold, not automatic rejection.
- Allow up to five minutes of controlled completion grace for a 30-minute interview.
- Require human review of final scorecards initially.
- Pause/end rather than silently changing TTS voice.
- Require role, approved JD intelligence, target level, duration, language, competency, rubric, and runtime policies before publication.

---

## 25. Definition of done

The interview brain is ready for production evaluation when:

1. It can conduct technical and non-technical interviews with the same universal system prompt. — **met**
2. It understands approved JD and resume facts with traceable provenance. — **met** (text docs; OCR pending)
3. It progresses from breadth to controlled depth. — **met**
4. It knows exactly what was asked and answered. — **met**
5. It maintains competency coverage and missing evidence. — **partial** (scoring coverage; live tracker evolving)
6. It resumes correctly after worker restart. — **met** (3-layer snapshots)
7. It does not repeat answered questions. — **met** (policy/ledger)
8. It does not silently change voice. — **not met** (M5 pending)
9. It closes naturally at the configured time. — **met** (time policy)
10. Every score is evidence-backed and reviewable. — **partial** (AI card + evidence; human review/override APIs pending)
11. Candidate data and protected characteristics are handled according to approved privacy and fairness policies. — **partial** (rules in prompt/policy; formal retention gates evolving)
12. Human reviewers can understand, correct, and audit the final assessment. — **not met** (no review/override UI yet)

