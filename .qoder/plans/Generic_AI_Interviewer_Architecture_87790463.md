# AI Interviewer — Domain-Agnostic Architecture Implementation Plan

Build strictly against the frozen "AI Interviewer Final System Architecture & Implementation Specification v1.0". STT/TTS stay on API-key providers now (Sarvam/Deepgram/ElevenLabs/OpenAI — already wired); GPU self-hosting later requires no architecture change.

## Root Cause of Surface-Level Non-Tech Interviews (verified in code)

1. `services/backend-api/brain/llm_extract.py:464` — competency synthesis prompt says "expert technical recruiter" with tech-only examples → a Sales JD yields skill-name chips, not competencies with anchors/lens
2. `services/voice-agent/products/interviewer/prompts.py:42,105-108` — system prompt hardcodes "If the current competency is DSA — ask DSA… For SQL… For ML… For Python:" → the LLM has zero guidance for non-tech depth → generic questions
3. `products/interviewer/validator.py:110-145,303-320` — TECH_HOOK_PHRASES/TOKENS/UNGROUNDED_TECH_TERMS only recognize technical substance → non-tech answers misjudged as shallow
4. `products/interviewer/coverage.py:217-243` — `_TECH_STEMS` evidence matching → non-tech depth evidence undetected → engine moves on without probing
5. `brain/compiler.py:242+` — competencies seeded from compact JD *skill labels* (creator chips own the plan) → no level anchors, no evaluation lens, no per-competency intents
6. `brain/defaults.py` — tech-biased default ladders

## Component Status Matrix (current vs target spec §4)

| Component | Status | Gap |
|---|---|---|
| 4.1 Admin Config Layer | PARTIAL | role/seniority/duration/competency chips only; no weight sliders, rigor dial, sections/modes |
| 4.2 Context Layer (resume/JD parse) | EXISTS (biased) | heuristic+LLM extractors with provenance + jd_hash exist; tech-recruiter bias to remove; overwrite-on-reupload to complete |
| 4.3 Rubric Synthesis Engine | **MISSING** | nothing synthesizes competencies/anchors/skills/intents/evaluation lens |
| 4.4 Blueprint schema | ~70% | has versioned+immutable definitions, rubric anchors (1-5), weight, probes, time policy; missing sections+modes+max_minutes, rigor, required_questions, depth_target, allowed_intents, evaluation_lens, weak/strong anchors |
| 4.5 Interview FSM | EXISTS | deterministic `decide_next_action`; no belief early-exit; single implicit section loop |
| 4.6 Intent Selector | PARTIAL | fixed 5-intent tech ladder, not blueprint-driven |
| 4.7 Context Builder / PromptContext | EXISTS (biased) | rich context; no anchors/mode/rigor/lens |
| 4.8 Generative Agent Layer | PARTIAL | single generic generator (no bank-primary — good); no per-mode generators |
| 4.9 Question Validator | EXISTS (biased) | fit/novelty/leak checks + regenerate; tech hooks to replace |
| 4.10 Voice pipeline | PARTIAL | API-key providers wired; Silero VAD fixed 0.3s threshold (not semantic); barge-in via LiveKit; no filler model |
| 4.11 Evaluator + Belief Judge | PARTIAL | per-turn AnswerEvaluation exists; Belief Judge (L/M/H + justification) **MISSING** |
| 4.12 Coverage Engine | EXISTS (biased) | intent/evidence tracking; no belief_converged; fixed thresholds |
| 4.13 Memory layers | EXISTS | RAM/Redis/Mongo; no rubric cache keyed by JD+role+seniority |
| 4.14 Scorecard | PARTIAL | evidence-linked + review status; no belief merge; review/override APIs pending |

---

## Phase 0 — Blueprint Schema Extension + Admin Configuration Layer
*Foundation, additive + feature-flagged, no behavior change. Spec §4.1, §4.4.*

**Backend:**
- `services/backend-api/models/brain.py`: add `QuestioningMode` Literal (`technical|behavioral|case|scenario|project_deep_dive|system_design`), `RigorLevel` (`screening|balanced|bar_raiser`), `SectionDefinition` (id, order, type, max_minutes, competency_ids, is_warmup), `LevelAnchors` (weak/strong; derive from existing 5-point RubricAnchor). Extend `CompetencyDefinition` with `required_questions`, `depth_target` (0.55–0.9), `allowed_intents`, `evaluation_lens` (optional). Extend `InterviewDefinitionDraft` with `sections` + `rigor`. Backward compat: definitions without sections auto-group into one `competency_assessment` section.
- New `brain/blueprint_formula.py` — spec §4.1 weight→behaviour formula, constants tunable in this one file: `required_questions = round(1 + (weight/100)*3)`, `max_probes = round(1 + (weight/100)*3)`, `min_probes = 1`, `depth_target = 0.55 + (weight/100)*0.35`, `time_budget_minutes = (weight/total_weight) * section_time_budget`.
- `brain/compiler.py`: emit new fields via the formula; `brain/publish.py`: validate sections/time budgets.

**Frontend:**
- `apps/voice-frontend/components/SetupForm.tsx` + `app/interviewer/admin/design/page.tsx`: per-competency weight sliders (total capped at 100), rigor dial, per-section questioning-mode selection, competency anchors preview.

**Exit criteria:** Backend Engineer AND Enterprise Sales Executive definitions representable without schema change; existing tech interviews byte-identical with flag off; formula unit tests green.
**Tests:** `services/backend-api/tests/test_blueprint_sections.py`, `test_weight_formula.py`; extend `apps/voice-frontend/tests/setup-flow.test.tsx`.

## Phase 1 — Rubric Synthesis Engine + Context Layer De-Biasing
*THE domain-agnostic unlock. Spec §4.2, §4.3.*

**Backend:**
- New `services/backend-api/brain/rubric_synthesis.py`: one LLM call after the Context Layer. Input: structured JD profile + role + seniority (+ resume/brief when present), channel-fenced. Output (strict JSON via existing `brain/structured_llm.py`): competencies **only for what the admin left unset** (admin-specified preserved verbatim), level anchors (weak/strong), required_skills per competency, allowed_intents, and the evaluation lens for that context (MEDDIC vs BANT vs SPIN vs STAR etc. — derived from JD signals, never a hardcoded domain list). Prompt is a domain-neutral "expert assessment designer", zero tech examples.
- `brain/llm_extract.py`: replace the "expert technical recruiter" prompt with the domain-neutral assessment-designer prompt.
- `brain/compiler.py`: consume synthesis output instead of skill-label seeding for unset competencies.
- Rubric cache: new Mongo collection `rubric_cache` keyed by sha256(JD text + role + seniority). Read-through performance layer only — a cache hit still produces a full versioned Blueprint; a miss always falls through to fresh synthesis, never a degraded/generic result.
- Re-upload fix: on `jd_hash` change, fully overwrite all derived state (competencies, Redis hot copies) — complete the existing jd_hash guardrail into full-overwrite semantics, never merge.
- Admin UI: "Synthesize competencies" action on the design page showing synthesized vs admin-defined items (source traceability), editable before publish.

**Exit criteria:** Enterprise-sales JD → MEDDIC-style competencies with anchors + required skills + intents; SMB vs Enterprise sales JDs produce provably different rubrics; admin competencies never overridden; cache miss falls through.
**Tests:** `test_rubric_synthesis.py` (fixtures: enterprise sales, SMB sales, HR generalist, backend engineer, free-text brief with no role), `test_rubric_cache.py`, `test_jd_reupload_overwrite.py`.

## Phase 2 — Domain-Neutral Live Engine (FSM / Generators / Validator / Coverage / Intents)
*Replaces the tech-biased runtime. Spec §4.5–4.9.*

**Voice agent (`services/voice-agent/products/interviewer/`):**
- `prompts.py`: delete the hardcoded DSA/SQL/ML/Python blocks (lines 42, 105-108). System prompt becomes purely structural (brain-plan §4.1 wording). Add per-mode prompt packs — technical, behavioral (STAR), case (setup/framework/quantitative/recommendation), scenario, project deep-dive, system design — selected by `section.type` from the Blueprint. Level anchors + evaluation lens ride in the turn payload.
- `policy.py`: add `MOVE_TO_NEXT_SECTION` action + section sequencing (warmup → blueprint sections → closing); enforce `required_questions` / `depth_target` / section `max_minutes` from the Blueprint. FSM stays 100% domain-agnostic — add a CI grep gate that fails on domain-name branching.
- Intent selector: driven by per-competency `allowed_intents` (synthesis/admin), not the global 5-intent tech ladder; no same intent twice in a row.
- `validator.py`: replace TECH_HOOK_PHRASES/TOKENS/UNGROUNDED_TECH_TERMS with Blueprint-derived hooks (required_skills + anchor terms per competency). Keep structural checks (novelty, leaked answer, drift) + regenerate-then-fallback.
- `coverage.py`: replace `_TECH_STEMS` with `evidence_expected`-driven matching (dynamic per competency, from the Blueprint).
- `flow.py`: extend PromptContext with section_type, level_anchor_weak/strong, evaluation_lens, rigor, missing_skills.
- `brain/defaults.py` (backend): domain-neutral fallback ladders.

**Exit criteria:** the same engine runs SDE + Sales + HR interviews differing only by Blueprint data; zero domain if/elif anywhere; replay tests show sales probing reaching anchor depth, not surface.
**Tests:** extend `test_interview_policy_flow.py`, `test_question_validator.py`, `test_interview_quality.py`; new `test_domain_neutral_prompts.py`, `test_section_sequencing.py`; replay-based `test_sales_depth.py` (uses `replay.py`).

## Phase 3 — Merged Evaluation Layer (Evaluator + Belief-Updating Judge)
*Spec §4.11, §4.12.*

- Pass 1 (extend): `AnswerEvaluation` gains `required_skills_demonstrated` (mapped from Blueprint required_skills) — feeds Coverage directly.
- New `products/interviewer/belief.py` + backend support: Belief Judge re-reads the full transcript (async, never blocks the turn), updates per-competency {low, medium, high} distribution + `belief_delta` + plain-language justification for every change; persisted in `InterviewBrainState` + Mongo (Appendix B shape).
- `coverage.py`: `competency_covered()` adds `belief_converged = belief_delta <= convergence_threshold`; thresholds configurable per rigor level (screening vs bar-raiser), not hardcoded.
- `policy.py`: belief early-exit ahead of the hard probe cap.
- `brain/scoring.py`: scorecard merges Coverage Engine hard stats + converged belief + justification log per competency.

**Exit criteria:** every belief update logs a justification; FSM closes converged competencies without waiting for max_probes; scorecard shows both mechanical coverage and belief with reasons; async judge adds zero turn latency.
**Tests:** `test_belief_judge.py`, `test_coverage_convergence.py`, `test_scorecard_belief_merge.py`.

## Phase 4 — Voice: Semantic Turn Detection + Barge-in + Filler Model
*Parallel track — independent of Phases 1-3. Spec §4.10.*

- Add `livekit-plugins-turn-detector` to `services/voice-agent/requirements.txt`; wire in `voice_platform/runtime.py` + `worker.py` as the default turn detector (semantic + acoustic fusion), keeping Silero VAD only as degradation fallback; config path to Deepgram Flux when `STT_PROVIDER=deepgram`.
- Verify barge-in end-to-end: candidate interruption cancels in-flight TTS cleanly and regenerates.
- Filler acknowledgments: a small fast model call ("Got it, let's dig into that…") masks generator latency; enforce budget via `latency.py`.
- Provider abstraction untouched — API keys today, GPU self-hosted later, no lock-in (turn detector works with any STT).

**Exit criteria:** no fixed-threshold cut-offs in test sessions; barge-in cancels speech cleanly; measured time-to-first-audio within the latency budget with filler active.
**Tests:** `test_turn_detection.py`, `test_barge_in.py`, `test_filler_latency.py` (mocked); extend `test_latency_budget.py`.

## Phase 5 — Channel Separation at All 4 LLM Call Sites + Monitoring
*Spec §6.*

- New `services/backend-api/brain/channel_separation.py`: fenced data-channel wrapper — sanitize + canonicalize text on ingestion (extend `safety.py`/`pii.py`), wrap in an explicitly inert data fence declared in the system prompt. Apply uniformly at: (1) Context Layer, (2) Rubric Synthesis, (3) Generative Agent Layer, (4) Evaluator/Belief Judge.
- Audit + enforce: LLM output crosses into the FSM only via schema-validated structured fields.
- Monitoring: log attack-success and false-rejection rates via existing structured logging (`observability.py`).

**Exit criteria:** injected resume/JD instructions (obvious + non-obvious variants from the benchmark corpus) never alter FSM behavior; false-rejection rate tracked.
**Tests:** `test_channel_separation.py` with an injection corpus.

## Phase 6 — Admin Test/Simulation Mode + Review/Override Completion
*Spec §7. Versioning/freezing already built — preserve and expose.*

- Backend: `POST /interview-brain/definitions/{id}/simulate` — runs a Blueprint against a simulated candidate (reuse `products/interviewer/replay.py` harness); returns question quality, pacing, and coverage report.
- Frontend: "Test run" button on the admin design page; Blueprint version history UI (Mongo versions already exist).
- Finish Milestone-6 pending items: scorecard review/override APIs (`POST …/scorecard/review`) + recruiter review UI on results/scorecard pages.

**Exit criteria:** admin simulates a Blueprint end-to-end pre-publish; reviewer can approve/override with reason; versions browsable.
**Tests:** `test_simulation_mode.py`, `test_scorecard_review_api.py`; extend `apps/voice-frontend/tests/scorecard-review.test.tsx`.

## Phase 7 — Cross-Domain Regression Suite (standing per-sprint gate)
*Spec §13.*

- Fixtures under `services/backend-api/tests/regression/cross_domain/` + `services/voice-agent/tests/regression/`: Senior SDE (backend, fintech); SMB Sales Executive (BANT JD) vs Enterprise Sales Executive (MEDDIC JD) — same title, provably different rubrics; HR generalist final round (behavioral/STAR only); free-text brief with no named role.
- Assertions: rubric distinctness, per-competency question depth (not surface), coverage completes, no domain branching (CI grep), belief justifications present in scorecards.
- Wire into `.github/workflows/ci.yml` as a standing gate.

**Exit criteria:** suite green on all five contexts; runs on every PR.

---

## Sequencing & Dependencies
- **0 → 1 → 2 → 3** strictly sequential (schema → synthesis → live engine → evaluation).
- **4** runs in parallel any time after Phase 0 (voice-only; API-key providers confirmed).
- **5** starts after Phase 1 (fence the new synthesis site first, then the other three during Phase 2/3).
- **6** after Phase 2 (simulation needs the new engine). **7** grows from Phase 1 onward, formalized last.
- Each phase ships independently; the product stays usable at every step.

## Non-Negotiable Rules (enforced throughout; spec §9)
1. FSM never branches on domain name (CI grep gate from Phase 2).
2. Rubric Synthesis never receives a hardcoded domain list — derives fresh from context every session.
3. Blueprint is the only interface between configuration/synthesis and the FSM.
4. All candidate/resume/JD text fenced as data at every LLM call site.
5. Live interviews always run the frozen Blueprint version (already built — preserve).
6. Rubric cache is performance-only; a miss falls through to full synthesis.
7. Static question bank is fallback-only after two failed generations (current no-bank-primary behavior preserved; fallback ladders domain-neutral).
8. Every belief update and coverage decision logs a human-readable justification.

## Test Plan
- Per-phase unit tests as listed above.
- All existing suites must stay green: `test_interview_policy_flow.py`, `test_question_validator.py`, `test_interview_quality.py`, `test_transcript_and_scoring.py`, `test_latency_budget.py`, `test_tts_*`, frontend vitest suites.
- Replay-based integration tests for depth/quality assertions; cross-domain suite as the standing gate.

## Assumptions
- LLM inference via the OpenAI-compatible path (self-hosted qwen or API). If the small self-hosted model cannot produce reliable structured synthesis, Phase 1 routes synthesis through a stronger API model behind the existing `LLM_*` settings.
- STT/TTS remain API-key providers for now; GPU migration is config-only.
- LiveKit Agents 1.8.1 accepts the turn-detector plugin (verify in Phase 4 spike before wiring).
- MongoDB + Redis available in staging (already required by the brain).
- Note: uncommitted local edits in `services/voice-agent/clients/tts/voice_policy.py` (Deepgram defaults) are unrelated to this plan — keep them out of scope.