# AI Interviewer Question Generation Context

## Purpose

This document describes the files and data used to generate each AI interviewer question, especially resume-aware follow-ups.

The system has two separate responsibilities:

- The policy layer decides what evidence, competency, and depth should come next.
- The LLM layer phrases that decision as one spoken question.

The LLM must not invent a new competency, skip the policy decision, or create facts that are not present in the interview context.

## End-to-end flow

```text
Resume upload or interview setup
  -> resume text and candidate profile
  -> interview context in backend storage
  -> LiveKit room metadata with context_id
  -> voice-agent worker fetches context
  -> AaptorAgent creates InterviewFlow
  -> InterviewFlow builds policy state and prompt context
  -> LLM evaluates the last answer and writes one question
  -> validator checks the generated question
  -> LiveKit speaks the accepted question through TTS
```

## Files that provide resume context

### Resume extraction

[services/backend-api/brain/extractors.py](../services/backend-api/brain/extractors.py)

Provides deterministic resume parsing and provenance-preserving extraction:

- Normalizes resume text.
- Finds resume sections.
- Extracts projects and candidate claims.
- Infers candidate profile type and seniority when possible.
- Builds structured resume and job-intelligence records.

The voice interviewer also contains a small project-title extractor for the live flow. It is in `services/voice-agent/products/interviewer/flow.py` and is used when raw resume text is available to the worker.

### LLM candidate-profile extraction

[services/backend-api/brain/llm_extract.py](../services/backend-api/brain/llm_extract.py)

Enriches extracted resume text into a candidate profile. The profile can contain:

- Experience summary.
- Candidate claims.
- Project claims.
- Seniority or profile framing.
- Source-backed resume facts.

### Candidate CV upload

[services/backend-api/routers/admin_candidates.py](../services/backend-api/routers/admin_candidates.py)

When a CV is uploaded, this route:

1. Extracts text from the uploaded file.
2. Calls candidate-profile extraction.
3. Stores `resume_text` and `candidate_profile` on the candidate record.

### Interview context storage

[services/backend-api/routers/interview_contexts.py](../services/backend-api/routers/interview_contexts.py)

Stores and returns the context used by the worker:

- `job_description`
- `resume_text`
- `interview_setup`
- `definition_id`
- `candidate_profile`

### Scheduled interview context assembly

[services/backend-api/routers/scheduled_interviews.py](../services/backend-api/routers/scheduled_interviews.py)

For an admin candidate, this route retrieves the stored candidate resume and copies it into the interview context before scheduling. It also carries the candidate profile and published interview definition.

### Session and room dispatch

[services/backend-api/routers/sessions.py](../services/backend-api/routers/sessions.py)

Creates the LiveKit room and dispatches the `aaptor` worker. The room/job metadata contains the `context_id` and session identifiers. The worker uses the context ID to retrieve the actual resume and JD instead of relying on large room metadata payloads.

## Files that load context into the interviewer

### Worker entrypoint

[services/voice-agent/products/interviewer/worker.py](../services/voice-agent/products/interviewer/worker.py)

The worker is the main context handoff:

1. Reads `context_id` from the LiveKit job metadata.
2. Calls the backend context API.
3. Loads `job_description`, `resume_text`, `interview_setup`, and `candidate_profile`.
4. Loads the published interview definition when `definition_id` is present.
5. Builds the interview outline.
6. Creates `AaptorAgent` with all context fields.

Important calls include:

- `fetch_interview_context()`
- `fetch_interview_definition()`
- `build_candidate_profile()`
- `enrich_outline_with_resume()`
- `AaptorAgent(...)`

### Agent wrapper

[services/voice-agent/products/interviewer/agent.py](../services/voice-agent/products/interviewer/agent.py)

Passes resume and candidate context into `InterviewFlow` and exposes the generated question to LiveKit.

It also records candidate and interviewer turns, answer evaluations, competency IDs, question depth, and source claim IDs.

## Files that decide the next follow-up

### Interview state and prompt context

[services/voice-agent/products/interviewer/flow.py](../services/voice-agent/products/interviewer/flow.py)

This is the most important file for resume-aware follow-ups.

It performs the following work:

- Extracts named resume projects with `extract_resume_projects()`.
- Creates candidate claims with `build_candidate_profile()`.
- Creates a local excerpt around the active project with `resume_project_excerpt()`.
- Selects the active resume project with `_ensure_focus()`.
- Tracks covered and uncovered projects and JD requirements.
- Maintains candidate turns, interviewer turns, competency coverage, known facts, probe shape, and policy state.
- Builds the prompt in `_structured_system_prompt()` and `_prompt_for_turn()`.
- Sends the candidate's last answer and the active resume excerpt to the LLM.
- Applies the policy decision after the answer is evaluated.
- Prevents repeated questioning and stops after repeated probes add no new evidence.

The resume context reaches the LLM through these prompt fields:

- `resume_project_context`
- `resume_excerpt`
- `resume_brief`
- `claim_brief`
- `active_focus`
- `active_focus_context`
- `known_facts`
- `last_turn`
- `recent_questions`

For a project follow-up, `resume_project_excerpt()` selects nearby lines around the project name. This keeps the prompt focused instead of sending an unrelated full resume section on every turn.

### Competency coverage ledger

[services/voice-agent/products/interviewer/coverage.py](../services/voice-agent/products/interviewer/coverage.py)

Tracks whether a competency's required intents have been covered. It provides:

- Required assessment intents.
- Covered intents.
- Missing intents.
- Evidence IDs.
- Partial or complete coverage status.
- Answer classification based on usability and evidence keywords.

The ledger prevents a resume claim from automatically being treated as demonstrated evidence.

### Authoritative policy

[services/voice-agent/products/interviewer/policy.py](../services/voice-agent/products/interviewer/policy.py)

Decides the next action independently of LLM wording:

- Open interview.
- Map candidate background.
- Ask a competency baseline.
- Probe for context, ownership, method, reasoning, or reflection.
- Clarify an unusable answer.
- Move to another competency.
- Offer a final addition.
- Close the interview.

It also enforces:

- Coverage before deeper probing.
- Maximum probe depth and probe count.
- Time limits.
- Non-answer handling.
- The two-consecutive-no-gain stop rule.

The LLM may phrase the selected action, but it cannot override a forced advance or close decision.

### Answer evaluation and question validation

[services/voice-agent/products/interviewer/validator.py](../services/voice-agent/products/interviewer/validator.py)

Defines the structured answer evaluation returned with a generated question. The evaluation includes:

- Technical substance: surface, partial, deep, incorrect, or not applicable.
- Key facts stated.
- Reasoning.
- Evidence match.
- Need for clarification.
- Factual correctness.
- Question metadata such as competency, intent, depth, probe shape, and source claim IDs.

It also validates question output and rejects malformed or unsafe generated content.

## Files that define the LLM instructions

### Prompt pack

[services/voice-agent/products/interviewer/prompts.py](../services/voice-agent/products/interviewer/prompts.py)

Defines the stable interviewer instructions and runtime prompt templates.

Important rules include:

- Ask one clear question per turn.
- Use only the supplied resume, JD, claims, definition, and previous answers.
- Anchor follow-ups to a concrete project, tool, decision, number, or outcome.
- Do not invent resume facts.
- Do not repeat already-established facts or question wording.
- Stay within the active competency.
- Increase depth by at most one rung.
- Prefer applied work over trivia.
- Keep questions short and spoken naturally.

The key templates are:

- `UNIVERSAL_SYSTEM_V2`
- `TURN_INSTRUCTIONS_V2`
- `OPENING_INSTRUCTIONS_V2`
- `ACTION_PHRASING`

## Files that persist brain and transcript state

### Brain state bridge

[services/voice-agent/products/interviewer/brain_runtime.py](../services/voice-agent/products/interviewer/brain_runtime.py)

Persists and restores the live interview state, including:

- Active competency.
- Active question ID.
- Asked question IDs.
- Candidate and interviewer turns.
- Coverage and evidence state.
- Answer evaluation.
- Policy action.

This prevents a reconnect from losing the question context or repeating the opening.

### Session persistence

[services/backend-api/routers/sessions.py](../services/backend-api/routers/sessions.py)

Coordinates session creation and room dispatch. The worker records turns and status through backend APIs so later questions can be based on the durable transcript when needed.

## Runtime question-generation sequence

For each candidate answer:

1. LiveKit delivers the candidate transcript to `AaptorAgent.llm_node()`.
2. The agent rejects empty, unusable, or obvious TTS-echo text.
3. `InterviewFlow` identifies the active competency and resume focus.
4. The policy computes the required next action and depth.
5. The prompt includes the active resume excerpt, claims, prior facts, prior questions, JD, and the latest answer.
6. The LLM evaluates the answer and proposes one question.
7. The validator checks the structured response.
8. Coverage and evidence state are updated.
9. The question is recorded and sent to LiveKit/TTS.
10. The next turn starts from the updated policy and evidence ledger.

## What the resume is allowed to do

The resume may:

- Select a concrete project or work example as an anchor.
- Provide facts for the opening.
- Provide tools, decisions, outcomes, and claims for follow-up questions.
- Help frame the candidate's experience level.
- Supply evidence that can be checked against a competency.

The resume may not:

- Create a new competency outside the published interview definition.
- Replace the JD or competency evidence requirements.
- Cause the interviewer to ask unrelated questions just because a keyword appears.
- Turn an unsupported claim into demonstrated evidence.
- Override policy decisions about depth, coverage, time, or closing.

## Example

If the resume contains:

```text
Project: Payment Retry Service
- Reduced failed payment retries by 30 percent.
- Added idempotency keys and exponential backoff.
```

A follow-up can use the nearby excerpt and ask:

```text
What failure mode led you to add idempotency keys?
```

The question is valid because it is:

- Anchored to a real resume project.
- Inside the active competency.
- About a concrete implementation decision.
- A single question.
- A natural next step in the probe ladder.

It should not instead ask a generic question such as `What is system design?` unless the active policy explicitly requires a baseline concept question.
