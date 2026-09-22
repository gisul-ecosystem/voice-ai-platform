# AI Interviewer Question Generation Source

## Claude Implementation Handoff

Use this document as a map of the question-generation system. The linked Python files are authoritative; code blocks in this document are orientation excerpts and must not be treated as a replacement for reading the current source.

### Objective

Make the interviewer ask one grounded follow-up at a time using the candidate's resume, the job description, the published competency definition, the candidate's latest answer, and the evidence already established.

### Non-negotiable behavior

1. The policy engine decides the next action, competency, intent, depth, and whether to probe, advance, or close.
2. The LLM phrases the policy decision; it must not override it.
3. Resume text may provide anchors and facts, but it must not create competencies outside the published definition.
4. Every question must be one question, grounded in the active competency, and different from prior questions.
5. Never treat a resume claim as demonstrated evidence without a concrete answer showing ownership, mechanism, result, or reasoning.
6. Do not ask trivia, puzzles, generic competency definitions, or unrelated questions.
7. Do not send an empty, duplicate, echo-derived, malformed, or unvalidated question to TTS.
8. After two consecutive probes add no new evidence, transition to the next uncovered competency or close.
9. Preserve the opening race guard. One LiveKit room must not produce two simultaneous interviewer utterances.

### Authoritative ownership map

| Responsibility | Authoritative file |
|---|---|
| Resume and candidate-profile extraction | `services/backend-api/brain/extractors.py`, `services/backend-api/brain/llm_extract.py` |
| Candidate CV persistence | `services/backend-api/routers/admin_candidates.py` |
| Interview context persistence and retrieval | `services/backend-api/routers/interview_contexts.py` |
| Candidate resume to scheduled interview context | `services/backend-api/routers/scheduled_interviews.py` |
| LiveKit room metadata and dispatch | `services/backend-api/routers/sessions.py` |
| Worker context loading | `services/voice-agent/products/interviewer/worker.py` |
| LiveKit interviewer adapter and speech concurrency | `services/voice-agent/products/interviewer/agent.py` |
| Interview state, resume focus, prompt input, and LLM call | `services/voice-agent/products/interviewer/flow.py` |
| Next-action policy and hard limits | `services/voice-agent/products/interviewer/policy.py` |
| Evidence ledger and answer heuristics | `services/voice-agent/products/interviewer/coverage.py` |
| LLM prompt contract | `services/voice-agent/products/interviewer/prompts.py` |
| LLM output and question validation | `services/voice-agent/products/interviewer/validator.py` |
| Durable question, answer, and brain state | `services/voice-agent/products/interviewer/brain_runtime.py` |
| STT/TTS provider event handling | `services/voice-agent/livekit_adapters.py` |

### Required investigation order

When changing question behavior, read files in this order:

1. `worker.py` to confirm which context reaches the agent.
2. `agent.py` to confirm turn ownership and concurrency.
3. `flow.py` to locate the prompt and state mutation.
4. `policy.py` and `coverage.py` to confirm the authoritative action.
5. `prompts.py` and `validator.py` to confirm the LLM contract.
6. `brain_runtime.py` to preserve reconnect and replay behavior.

Do not begin by changing prompt wording if the policy state is wrong. Do not add a second question-generation path.

### Runtime data contract

`worker.py` must pass these values into `AaptorAgent` and `InterviewFlow`:

```python
job_description: str
resume_text: str
interview_setup: dict | None
candidate_profile: dict | None
interview_definition: dict | None
competencies: list[str]
```

`flow.py` uses the following runtime context to build a question:

```python
{
    "active_competency": current competency definition,
    "policy_action": authoritative next action,
    "intent": required evidence intent,
    "depth": allowed ladder depth,
    "active_focus": selected resume project or JD focus,
    "active_focus_context": nearby resume excerpt,
    "claim_brief": allowed candidate claims,
    "known_facts": facts already stated for the competency,
    "missing_intents": evidence still required,
    "recent_turns": recent candidate answers,
    "recent_questions": questions already asked,
    "last_turn": latest candidate answer,
    "job_target_level": assessment seniority,
}
```

The LLM response must be parsed as a structured `GeneratedQuestion` containing a spoken `question`, `competency_id`, `intent`, `depth`, `decision`, optional `source_claim_ids`, `probe_shape`, and `answer_evaluation`.

### Safe change protocol

For any question-generation change:

1. State the local behavior hypothesis.
2. Add or update a focused test that can falsify it.
3. Change the smallest owning function.
4. Run the focused test before broad tests.
5. Confirm that the question is recorded once and spoken once.
6. Run the full voice-agent test suite before restarting the worker.

### Validation commands

```powershell
cd services\voice-agent
python -m pytest tests/test_interview_policy.py tests/test_interview_policy_flow.py -q
python -m pytest tests/test_agent_compatibility.py tests/test_interview_stream.py -q
python -m pytest -q
```

For live validation, run only one Aaptor worker. It must register as `aaptor` and listen on port `8081`.

## Source reference

This document contains the relevant source code used to load context, decide follow-ups, generate questions, validate them, and deliver them through LiveKit.

The excerpts are grouped in runtime order. For the complete implementation, open the linked source file.

## Runtime flow

```text
backend resume/JD storage
  -> worker context loading
  -> AaptorAgent
  -> InterviewFlow
  -> policy decision
  -> prompt construction
  -> LLM response
  -> validator
  -> LiveKit/TTS
```

## 1. Resume extraction

Source: [services/backend-api/brain/extractors.py](../services/backend-api/brain/extractors.py)

The backend extracts structured candidate information before the live interview.

```python

def extract_resume_projects(resume_text: str) -> list[str]:
    lines = (resume_text or "").splitlines()
    titles: list[str] = []
    in_section = False

    for line in lines:
        if _SECTION_HEADINGS.match(line):
            in_section = True
            continue

        inline = _INLINE_PROJECTS.match(line)
        if inline:
            rest = re.split(
                r"(?i)\b(skills|education|experience|certifications)\b",
                inline.group(1),
                maxsplit=1,
            )[0]
            for part in re.split(r"[;•]|\s+\|\s+", rest):
                title = _project_title(part)
                if title and title.lower() not in {"project", "projects"}:
                    titles.append(title)
            continue

        if in_section and _NEXT_HEADING.match(line):
            in_section = False
            continue

        labeled = _PROJECT_LABEL.match(line)
        if labeled:
            title = _project_title(labeled.group(1))
            if title:
                titles.append(title)
            continue

        if in_section:
            bullet = _BULLET.match(line)
            candidate = bullet.group(1) if bullet else line.strip()
            title = _project_title(candidate)
            if title and not _NEXT_HEADING.match(title):
                titles.append(title)

    seen: set[str] = set()
    unique: list[str] = []
    for title in titles:
        key = title.lower()
        if key in seen or key in {"project", "projects"}:
            continue
        seen.add(key)
        unique.append(title)
        if len(unique) >= 12:
            break
    return unique
```

The extracted project names become resume anchors. Raw resume text is retained for evidence and prompt excerpts.

## 2. Candidate CV upload

Source: [services/backend-api/routers/admin_candidates.py](../services/backend-api/routers/admin_candidates.py)

```python
@router.post(
    "/{candidate_id}/resume",
    response_model=CandidateResponse,
)
async def upload_candidate_resume(
    candidate_id: str,
    file: UploadFile = File(...),
) -> CandidateResponse:
    candidate = await candidates.get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    raw = await file.read()
    extracted = extract_document_text(
        data=raw,
        filename=file.filename or "resume",
        content_type=file.content_type,
    )
    profile = await extract_candidate_profile_async(extracted.text)

    await candidates.attach_resume(
        candidate_id,
        resume_text=extracted.text,
        candidate_profile=profile.model_dump(mode="python"),
        filename=extracted.filename,
        content_type=extracted.content_type,
    )

    return CandidateResponse(
        candidate_id=candidate_id,
        name=candidate["name"],
        email=candidate["email"],
        resume_uploaded=True,
        resume_filename=extracted.filename,
    )
```

The exact upload helper may vary by branch; the important contract is that `resume_text` and `candidate_profile` are saved on the candidate record.

## 3. Interview context storage

Source: [services/backend-api/routers/interview_contexts.py](../services/backend-api/routers/interview_contexts.py)

```python
@router.post(
    "",
    response_model=CreateInterviewContextResponse,
    dependencies=[Depends(require_bff_service), Depends(require_capacity)],
)
async def create_interview_context(
    req: CreateInterviewContextRequest,
) -> CreateInterviewContextResponse:
    stored = await interviews.create_context(
        req.job_description.strip(),
        req.resume_text.strip(),
        req.interview_setup.model_dump(mode="python")
        if req.interview_setup
        else None,
        definition_id=req.definition_id,
    )
    return CreateInterviewContextResponse(**stored)


@router.get(
    "/{context_id}",
    response_model=InterviewContextResponse,
    dependencies=[Depends(require_worker_service)],
)
async def read_interview_context(context_id: str) -> InterviewContextResponse:
    stored = await interviews.get_context(context_id)
    if stored is None:
        raise HTTPException(status_code=404, detail="Interview context not found")

    return InterviewContextResponse(
        context_id=context_id,
        job_description=stored["job_description"],
        resume_text=stored["resume_text"],
        interview_setup=stored.get("interview_setup"),
        definition_id=stored.get("definition_id"),
        candidate_profile=stored.get("candidate_profile"),
    )
```

The worker retrieves this context using `context_id` from the LiveKit job metadata.

## 4. Scheduled interview assembly

Source: [services/backend-api/routers/scheduled_interviews.py](../services/backend-api/routers/scheduled_interviews.py)

```python
candidate_id = (req.candidate_id or "").strip() or None
candidate_record = None

if candidate_id:
    candidate_record = await candidates.get_candidate(candidate_id)
    if candidate_record is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if not (candidate_record.get("resume_text") or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Candidate CV must be uploaded first",
        )

 effective_resume_text = (
    candidate_record["resume_text"]
    if candidate_record
    else (req.resume_text or "").strip()
)

context = await interviews.create_context(
    req.job_description.strip(),
    effective_resume_text,
    req.interview_setup.model_dump(mode="python"),
    definition_id=published.definition_id,
    candidate_profile=(candidate_record or {}).get("candidate_profile"),
)
```

This is where the stored candidate resume becomes the resume used by the specific interview.

## 5. Worker context loading

Source: [services/voice-agent/products/interviewer/worker.py](../services/voice-agent/products/interviewer/worker.py)

```python
async def plan_inputs_from_job(ctx: JobContext) -> tuple[str, str]:
    context_id = context_id_from_job(ctx)
    if context_id:
        context = await fetch_interview_context(context_id)
        return (
            str(context.get("job_description") or "").strip(),
            str(context.get("resume_text") or "").strip(),
        )

    if (os.getenv("APP_ENV") or "development").lower() not in {
        "production",
        "staging",
    }:
        return (
            (os.getenv("JOB_DESCRIPTION") or "").strip(),
            (os.getenv("RESUME_TEXT") or "").strip(),
        )

    return "", ""
```

```python
context_id = context_id_from_job(ctx)
context = await fetch_interview_context(context_id) if context_id else {}

job_description = str(context.get("job_description") or "").strip()
resume_text = str(context.get("resume_text") or "").strip()
interview_setup = context.get("interview_setup")

candidate_profile = build_candidate_profile(
    resume_text=resume_text,
    interview_setup=interview_setup,
    definition=interview_definition,
    existing=context.get("candidate_profile"),
)

await session.start(
    agent=AaptorAgent(
        outline,
        clients.llm,
        job_description=job_description,
        resume_text=resume_text,
        competencies=competencies,
        candidate_profile=candidate_profile,
        interview_definition=interview_definition,
    ),
    room=ctx.room,
)
```

## 6. Agent context handoff

Source: [services/voice-agent/products/interviewer/agent.py](../services/voice-agent/products/interviewer/agent.py)

```python
class AaptorAgent(Agent):
    def __init__(
        self,
        outline: dict,
        llm_client,
        *,
        job_description: str = "",
        resume_text: str = "",
        competencies: list[str] | None = None,
        interview_definition: dict | None = None,
        candidate_profile: dict | None = None,
        **kwargs,
    ) -> None:
        super().__init__(
            instructions=(
                "You are Aaptor, a live technical interviewer. Invent each "
                "spoken question from the resume, job, and the candidate's "
                "last answer. Sound like a person in the room."
            )
        )

        flow_kwargs = {
            "job_description": job_description,
            "resume_text": resume_text,
            "competencies": competencies or [],
            "interview_definition": interview_definition,
            "candidate_profile": candidate_profile,
        }
        self.flow = InterviewFlow(outline, llm_client, **flow_kwargs)
```

`AaptorAgent.llm_node()` later sends the generated question to LiveKit and records the candidate/interviewer exchange.

## 7. Resume-aware flow helpers

Source: [services/voice-agent/products/interviewer/flow.py](../services/voice-agent/products/interviewer/flow.py)

### Resume project excerpt

```python
def resume_project_excerpt(
    resume_text: str,
    project_name: str,
    *,
    limit: int = 900,
) -> str:
    """Pull resume lines around a named project."""
    cleaned = (resume_text or "").strip()
    name = (project_name or "").strip()

    if not cleaned:
        return "(resume not provided)"
    if not name:
        return clip_source_text(cleaned, limit)

    lines = cleaned.splitlines()
    hits = [
        index
        for index, line in enumerate(lines)
        if _item_mentioned(name, line)
    ]

    if not hits:
        return clip_source_text(cleaned, limit)

    chunks: list[str] = []
    seen: set[int] = set()
    for hit in hits[:3]:
        start = max(0, hit - 1)
        end = min(len(lines), hit + 4)
        for index in range(start, end):
            if index in seen:
                continue
            seen.add(index)
            text = lines[index].strip()
            if text:
                chunks.append(text)

    excerpt = " ".join(chunks)
    return clip_source_text(excerpt, limit)
```

### Candidate profile and resume claims

```python
def build_candidate_profile(
    *,
    resume_text: str = "",
    interview_setup: dict | None = None,
    definition: dict | None = None,
    existing: dict | None = None,
) -> dict:
    if isinstance(existing, dict) and existing.get("claims"):
        profile = dict(existing)
    else:
        claims = [
            {
                "claim_id": f"claim_project_{index}",
                "type": "project",
                "value": name,
            }
            for index, name in enumerate(
                extract_resume_projects(resume_text),
                start=1,
            )
        ]
        profile = {
            "experience_summary": {"profile_type": "unknown"},
            "claims": claims,
            "raw_resume_text": resume_text,
        }

    setup = interview_setup if isinstance(interview_setup, dict) else {}
    role = {}
    if isinstance(definition, dict):
        intelligence = definition.get("job_intelligence")
        if isinstance(intelligence, dict):
            role = intelligence.get("role") or {}

    profile["job_target_level"] = (
        str(
            role.get("target_level")
            or setup.get("seniority")
            or "mid"
        ).strip()
        or "mid"
    )
    return profile
```

### Active resume focus

```python
def _ensure_focus(
    self,
    last_turn: str | None,
    *,
    is_intro_reply: bool = False,
) -> None:
    intent = self._turn_intent(is_intro_reply=is_intro_reply)

    if intent == "resume_project":
        if self.focus_item and self.focus_item.lower() not in self._touched_topics:
            return

        uncovered = self._uncovered_projects()
        named = self._project_from_text(last_turn)
        if named and named in uncovered:
            self.focus_item = named
            return

        self.focus_item = (
            uncovered
            or self.resume_projects
            or [self.focus_item or "this project"]
        )[0]
```

### Resume context added to the candidate turn

```python
def _user_turn_content(
    self,
    last_candidate_turn: str,
    *,
    is_intro_reply: bool,
) -> str:
    previous = self.interviewer_turns[-1] if self.interviewer_turns else ""
    earlier = self.candidate_turns[-3:]
    parts = []

    if is_intro_reply:
        parts.append(
            "The candidate just introduced themselves. Use the whole intro."
        )
    if previous:
        parts.append(f"Your previous question:\n{previous}")
    if earlier:
        parts.append(
            "Earlier answers in this thread:\n"
            + "\n".join(f"- {turn}" for turn in earlier)
        )

    parts.append(f"Latest answer, in full:\n{last_candidate_turn.strip()}")

    if self._phase_intent() in {"intro", "resume_project"} or is_intro_reply:
        parts.append(
            f"Resume facts for {self.focus_item or 'this project'}:\n"
            f"{self._resume_project_context()}"
        )

    return "\n\n".join(parts)
```

### Question generation entrypoint

```python
async def generate_next_question(
    self,
    last_candidate_turn: str | None,
) -> str:
    last_candidate_turn = (last_candidate_turn or "").strip() or None

    closing = self._closing_speech(last_candidate_turn)
    if closing:
        return closing

    if last_candidate_turn and self.policy_mode:
        is_intro_reply = not self.candidate_turns
        self._record_answer_quality(
            last_candidate_turn,
            is_intro_reply=is_intro_reply,
        )

    prompt, user_content = self._prompt_for_turn(last_candidate_turn)
    raw = await self.llm_client.generate_reply(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ],
        extra_body={"max_completion_tokens": 256},
    )

    generated = self._coerce_generated(
        raw,
        policy=self.last_policy_decision,
        last_candidate_turn=last_candidate_turn,
    )
    self._remember_generated(generated, self.last_policy_decision)
    self._refine_answer_quality(last_candidate_turn, generated)

    if last_candidate_turn:
        self.candidate_turns.append(last_candidate_turn)
        self._apply_turn_decision(
            generated.decision,
            is_intro_reply=not self.candidate_turns,
        )

    self._remember_question(generated.question)
    return generated.question
```

## 8. Policy decision

Source: [services/voice-agent/products/interviewer/policy.py](../services/voice-agent/products/interviewer/policy.py)

```python
@dataclass
class PolicyState:
    candidate_turn_count: int = 0
    interviewer_turn_count: int = 0
    phase_index: int = 0
    probe_count: int = 0
    consecutive_unusable: int = 0
    consecutive_no_gain_probes: int = 0
    competency_id: str | None = None
    max_depth: int = 4
    max_probes: int = 3
    missing_intents: list[str] = field(default_factory=list)
    has_uncovered_competencies: bool = False
```

```python
if state.consecutive_no_gain_probes >= 2:
    return PolicyDecision(
        action=(
            MOVE_TO_NEXT_COMPETENCY
            if state.has_uncovered_competencies
            else OFFER_FINAL_ADDITION
        ),
        forced_flow_decision=(
            "advance" if state.has_uncovered_competencies else "close"
        ),
        allow_llm_decision=False,
        current_depth=1,
        max_depth=state.max_depth,
        competency_id=state.competency_id,
        intent="evidence_gap_stop",
        reason="two consecutive probes added no new evidence",
        section=_section_for_phase(state.phase_name),
    )
```

The policy decides the action. The LLM only phrases the action.

## 9. Coverage ledger

Source: [services/voice-agent/products/interviewer/coverage.py](../services/voice-agent/products/interviewer/coverage.py)

```python
def empty_coverage_entry(required: list[str]) -> dict[str, Any]:
    return {
        "status": "not_started",
        "required_intents": list(required),
        "covered_intents": [],
        "missing_intents": list(required),
        "evidence_ids": [],
    }
```

```python
def apply_coverage(
    coverage: dict[str, dict[str, Any]],
    *,
    competency_id: str | None,
    covered_intents: list[str],
    evidence_id: str | None = None,
    answer_eval: Any | None = None,
) -> dict[str, dict[str, Any]]:
    if not competency_id or competency_id not in coverage:
        return coverage

    entry = dict(coverage[competency_id])
    required = list(entry.get("required_intents") or [])
    already = list(entry.get("covered_intents") or [])

    for intent in covered_intents:
        if intent in required and intent not in already:
            already.append(intent)

    missing = [intent for intent in required if intent not in already]
    evidence_ids = list(entry.get("evidence_ids") or [])
    if evidence_id and evidence_id not in evidence_ids:
        evidence_ids.append(evidence_id)

    status = "complete" if already and not missing else "partial" if already else "not_started"
    if status == "complete" and quality_from_evaluation(answer_eval) == "unclear":
        status = "insufficient_evidence"

    coverage[competency_id] = {
        "status": status,
        "required_intents": required,
        "covered_intents": already,
        "missing_intents": missing,
        "evidence_ids": evidence_ids,
    }
    return coverage
```

## 10. LLM prompt instructions

Source: [services/voice-agent/products/interviewer/prompts.py](../services/voice-agent/products/interviewer/prompts.py)

```python
UNIVERSAL_SYSTEM_V2 = """You are a professional structured interviewer speaking live.

Conduct a fair, job-related interview using only the supplied interview definition and next action.

Rules:
- Ask one clear question at a time.
- Follow the supplied competency, objective, intent, and allowed depth.
- Use candidate facts only when they appear in the supplied claims, resume excerpt,
  job text, or last answers.
- Do not invent employers, projects, tools, metrics, or skills.
- Do not repeat a question that was already asked.
- Ask one conversational question that naturally follows from the answer.
- Speak 1-2 short sentences and use plain language.
"""
```

```python
TURN_INSTRUCTIONS_V2 = """POLICY ENGINE (authoritative — do not override):
- Required next action: {action}
- Intent: {intent}
- Allowed depth now: {current_depth} of {max_depth}
- Flow decision must be: {forced_flow_decision}

Current competency: {competency_name} ({competency_id})
Active JD/resume focus: {active_focus}
Active focus source context:
{active_focus_context}
Missing required intents: {missing_intents}
Evidence still needed: {evidence_expected}
Facts already established:
{known_facts}
Questions already asked:
{recent_questions}
Last answer:
{last_turn}

Anchor the question in the active JD/resume focus.
Do not ask a generic definition question unless the policy explicitly requires it.
Do not repeat an established fact.
Ask one question only.
"""
```

The live prompt also receives the resume excerpt, candidate claims, seniority guidance, JD excerpt, prior turns, and answer evaluation.

## 11. Answer evaluation and validation

Source: [services/voice-agent/products/interviewer/validator.py](../services/voice-agent/products/interviewer/validator.py)

```python
@dataclass
class AnswerEvaluation:
    technical_substance: str = "not_applicable"
    key_facts_stated: list[str] = field(default_factory=list)
    reasoning: str = ""
    matches_evidence_expected: bool = False
    needs_clarification: bool = False
    factually_correct: bool = True
```

The prompt asks the LLM to return answer evaluation and question metadata together. The validator parses the structured response before the question is recorded and spoken.

## 12. LiveKit delivery

Source: [services/voice-agent/products/interviewer/agent.py](../services/voice-agent/products/interviewer/agent.py)

```python
async def llm_node(
    self,
    chat_ctx: llm.ChatContext,
    tools: list,
    model_settings: ModelSettings,
):
    candidate_turn = last_text(chat_ctx)

    if self._opening_in_progress or (self._opened and not candidate_turn):
        return

    if not is_usable_candidate_turn(
        candidate_turn,
        self._last_agent_text,
        min_words=1 if not self.flow.candidate_turns else 3,
    ):
        yield CLARIFY_TURN
        return

    parts: list[str] = []
    async for chunk in self.flow.generate_next_question_stream(candidate_turn):
        parts.append(chunk)
        yield chunk

    question = "".join(parts).strip()
    if question:
        self._last_agent_text = question
        await self._record("agent", question)
        await self._persist_brain_after_exchange(
            speaker="agent",
            text=question,
            turn_id=None,
        )
```

The LiveKit adapter then sends the generated text to the configured TTS provider.

## 13. Complete source index

- [extractors.py](../services/backend-api/brain/extractors.py): resume and JD extraction.
- [admin_candidates.py](../services/backend-api/routers/admin_candidates.py): CV upload and candidate storage.
- [interview_contexts.py](../services/backend-api/routers/interview_contexts.py): interview context API.
- [scheduled_interviews.py](../services/backend-api/routers/scheduled_interviews.py): candidate resume to interview context handoff.
- [sessions.py](../services/backend-api/routers/sessions.py): LiveKit room and worker dispatch.
- [worker.py](../services/voice-agent/products/interviewer/worker.py): context loading and agent startup.
- [agent.py](../services/voice-agent/products/interviewer/agent.py): LiveKit agent wrapper.
- [flow.py](../services/voice-agent/products/interviewer/flow.py): resume-aware prompt construction and question generation.
- [policy.py](../services/voice-agent/products/interviewer/policy.py): authoritative next-action policy.
- [coverage.py](../services/voice-agent/products/interviewer/coverage.py): competency evidence ledger.
- [prompts.py](../services/voice-agent/products/interviewer/prompts.py): LLM system and turn instructions.
- [validator.py](../services/voice-agent/products/interviewer/validator.py): structured output and answer evaluation validation.
- [brain_runtime.py](../services/voice-agent/products/interviewer/brain_runtime.py): durable brain/question state.
- [livekit_adapters.py](../services/voice-agent/livekit_adapters.py): STT/TTS event and speech adapter behavior.
