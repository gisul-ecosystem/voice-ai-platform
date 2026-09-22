# AI Interviewer — End-to-End Sprint Plan (Azure ready)

**Azure project:** [AI-Interviewer](https://dev.azure.com/Gisul/AI-Interviewer) (org: Gisul)  
**Iteration / sprint:** `Sprint 2026-09-15` — **2026-09-15 → 2026-09-30** (to end of month)  
**Plan date:** 2026-09-18  
**Lead:** **Ujwal Kulal** (`ujwal.kulal@gisul.co.in`) — board, staging, validation, unblocks team  
**Team:**  
- Abhijeet Singh — `abhijeet.singh@gisul.co.in` (speech / TTS)  
- Aditya Bargujar — `aditya.bargujar@gisul.co.in` (live interview intelligence)  
- Akshay Krishnan — `Akshay.Krishnan@gisul.co.in` (structured scoring / scorecard)  
**Capacity:** ~47 SP (Abhijeet 13 · Aditya 13 · Akshay 13 · Ujwal 8)  
**Epic:** AI Interviewer production readiness — voice, live intelligence, structured scoring

> **Access note:** Stakeholder license cannot create iterations or most work items. **Ujwal (Lead)** needs **Basic+** to run `docs/azure_push_sprint.ps1`.

---

## 1. Sprint goal

Ship a production-ready interview path for **2026-09-15 → 2026-09-30**:

1. Stable **pinned voice** and clean speech (no echo/transcript chaos)  
2. **JD/resume-aware** live questioning with experience framing  
3. **Structured assessment** — must-have vs nice-to-have, validated questions, evidence-only scores  
4. **Recruiter scorecard UI** with approve/override  
5. Staging **Redis** memory + end-to-end validation matrix  

---

## 2. Research baseline

### Product E2E that already works

```text
Setup → ingest JD/resume → schedule (auto-publish definition + invite)
  → attend → consent → prejoin → live policy interview → turns + brain
  → completed → AI scorecard (API) → review API exists (no UI yet)
```

### Open production gaps (this sprint)

| Gap | Owner |
|-----|--------|
| Mid-session voice change / no TTS pin | Abhijeet |
| Echo / messy transcript turns | Abhijeet |
| Context/memory proven on staging | Ujwal + Aditya |
| Opening ignores JD/resume | Aditya |
| Experience framing for same JD | Aditya |
| Non-answer end + time grace + close | Aditya |
| Anti-trivia, level-appropriate questions | Aditya |
| Creator publication gates | Ujwal |
| Must/nice + recruiter scorecard UI | Akshay |

### Code vs structured interviewing product

| Product claim | Code today | Gap |
|---------------|------------|-----|
| JD/competencies primary; resume personalizes | Policy + weights exist; opening still generic | Aditya opening + Akshay scorecard copy |
| Must-have vs nice-to-have | Compiler weights + `importance` | Expose on definition + scorecard UI |
| Question ↔ skill/goal/difficulty/evidence | Ladders + validator | Persist metadata; harden fixtures |
| Evidence-only scoring | `brain/scoring.py` + tests | Close thin-claim holes; quality on card |
| Recruiter scorecard + override | Backend review APIs | **BFF + UI** |

---

## 3. Ownership map (no double work)

| Person | Email | Owns | Does **not** own |
|--------|-------|------|------------------|
| **Ujwal** (Lead) | ujwal.kulal@gisul.co.in | Staging/Redis, validation matrix, board, publication gates | Deep scoring algorithm |
| **Abhijeet** | abhijeet.singh@gisul.co.in | Speech latency, echo gate, pinned TTS | Scorecard UI |
| **Aditya** | aditya.bargujar@gisul.co.in | Opening, claims, experience framing, non-answer/time/close | Recruiter scorecard page |
| **Akshay** | Akshay.Krishnan@gisul.co.in | Must/nice, question validation, evidence scoring, **scorecard UI** | Echo/TTS, opening copy |

**Handoff:** Aditya’s live questions must emit competency_id/intent that Akshay’s scorecard can cite. Akshay’s must/nice weights must be what Aditya’s policy already loads from the definition.

---

## 4. Azure structure

| Type | Title | Assignee |
|------|--------|----------|
| Epic | AI Interviewer production readiness — voice, live intelligence, structured scoring | Ujwal |
| Feature | Speech quality, echo control, and session-pinned TTS voice | Abhijeet |
| Feature | Live interview intelligence — opening, claims, experience framing | Aditya |
| Feature | Structured interviewing — must/nice, validation, recruiter scorecard | Akshay |
| Feature | Staging, Redis brain memory, and production validation (Lead) | Ujwal |

Tags: `voice-ai` `speech` `brain` `scoring` `ops` `m5` `lead`

---

## 5. Abhijeet Singh — Speech + voice (13 SP) · `abhijeet.singh@gisul.co.in`

### PBI-A1 — Latency and transcript quality measurement harness (3 SP)

**Title:** `Latency and transcript quality measurement harness`

**Description**  
Repeatable measurements for speech-end→transcript, transcript→first token, first-token→first audio, speech-end→first audio. Capture p50/p95, duplicate-final rate, clarify-loop rate. Fixture set: short/long/pause/noise/barge-in/echo.

**Acceptance**
- [ ] Documented command reproduces baseline without PII/keys  
- [ ] Baseline saved for Sarvam + OpenAI + ElevenLabs  

### PBI-A2 — Hard echo and barge-in gate while agent is speaking (5 SP)

**Title:** `Hard echo and barge-in gate while agent is speaking`

**Description**  
While agent speaks, suppress candidate STT finals (hard gate). Keep intentional barge-in. Fix candidate mis-attribution of agent speech.

**Acceptance**
- [ ] Laptop-speaker test: agent lines ≠ candidate turns  
- [ ] Clarify-loop rate down vs baseline  

### PBI-A3 — Session-pinned TTS voice with preflight (5 SP)

**Title:** `Session-pinned TTS voice with preflight — no mid-session voice change`

**Description**  
Pin `voice_id` at session start; preflight; retry same voice only; pause/end on failure — never switch voice mid-session.

**Acceptance**
- [ ] Failure path never changes voice_id  
- [ ] One pinned voice logged per session  

---

## 6. Aditya Bargujar — Live intelligence (13 SP) · `aditya.bargujar@gisul.co.in`

### PBI-B1 — JD/resume-aware opening (5 SP)

**Title:** `JD and resume-aware interview opening`

**Description**  
Stop always speaking only `FALLBACK_OPENING`. Opening must cite one resume claim or JD signal when context exists; fallback only on failure. Resume personalizes — does not replace must-have competencies.

**Acceptance**
- [ ] With context → opening names a real claim/JD signal  
- [ ] Without context → generic opening still works  
- [ ] No full resume dump  

### PBI-B2 — Claims, experience framing, project ranking (5 SP)

**Title:** `Live resume claims, experience framing, and JD-based project ranking`

**Description**  
Prefer brain/context claims; frame by experience (final-year/BCA/MCA) without lowering job bar; rank projects by competency gap (plan §12).

**Acceptance**
- [ ] Same JD + different experience → different framing, same required competencies  
- [ ] Ranked project order unit-tested  
- [ ] Job bar not silently lowered  

### PBI-B3 — Non-answer ladder, time grace, closing, anti-trivia (3 SP)

**Title:** `Non-answer ladder, time-boundary grace, closing, and anti-trivia`

**Description**  
4 unusable → controlled close; ~5 min grace at 30 min; proper closing; block trivia/full-form when not job-critical.

**Acceptance**
- [ ] 4-unusable fixture closes controllably  
- [ ] Grace path verified  
- [ ] Closing always present on completed path  
- [ ] Anti-trivia fixtures pass  

---

## 7. Akshay Krishnan — Structured interviewing (13 SP) · `Akshay.Krishnan@gisul.co.in`

**Product brief (source of truth for this track):** Job-based interviewing, must-have vs nice-to-have, question generation & validation, evidence-based scoring, recruiter scorecard. Advisory only — humans decide hire/no-hire.

**Code home:**  
`services/backend-api/brain/{compiler,publish,scoring,scoring_service,quality}.py`  
`services/backend-api/models/brain.py`  
`services/backend-api/routers/session_events.py`  
`services/voice-agent/products/interviewer/validator.py` (contract tests / hooks with Aditya)  
`apps/voice-frontend` scorecard BFF + new results UI  

---

### PBI-C1 — Must-have vs nice-to-have end-to-end (3 SP)

**Title:** `Must-have vs nice-to-have competencies end-to-end`

**Description**  
Product rule: must-haves carry evaluation weight; nice-to-haves are supplementary and must not lower the required bar. Compiler already maps required vs preferred into weights (`_importance_weights`) and competencies have `importance` + `weight`. This PBI makes the distinction **explicit, visible, and testable** from published definition → live coverage priority → scorecard.

**Tasks**
- Ensure published definition marks each competency as must-have vs nice-to-have (map from JD required vs preferred / `importance` / weight bands).  
- Scorecard shows must-have vs nice-to-have sections; overall recommendation weights must-haves higher.  
- Tests: missing must-have evidence → `not_assessed` / insufficient overall; missing only nice-to-have does not fail the must-have bar.  
- Short doc note in scorecard UI copy: “Resume personalizes questions; required evidence is JD-defined.”

**Acceptance**
- [ ] Published definition exposes must vs nice for every competency  
- [ ] Scorecard UI/API payload separates the two  
- [ ] Automated test: Kafka-as-preferred missing ≠ fail Python-as-required when Python evidenced  
- [ ] Weights on scored must-haves drive overall recommendation  

---

### PBI-C2 — Question metadata + validation productization (3 SP)

**Title:** `Question validation — skill, goal, difficulty, and evidence criteria`

**Description**  
Every asked question must be associated with skill (competency), goal (intent), difficulty/level, and evidence criteria. Irrelevant, duplicate, unfair, or protected-attribute questions are rejected and replaced with a safe fallback. Validator exists in the worker; this PBI hardens the **product contract**: durable question records carry the metadata, validation failures are observable, and a fixture suite proves rejection/replacement.

**Tasks**
- Ensure persisted questions (brain Q ledger / turns linkage) store competency_id, intent/goal, depth/difficulty, evidence_expected.  
- Expand validation fixtures: off-topic, duplicate, protected markers, unfair.  
- On reject → safe fallback question for same competency/intent (coordinate with Aditya if flow hook needed).  
- Log/metric: `question_validation_rejected` with reason code (no PII).

**Acceptance**
- [ ] Fixture suite: protected / duplicate / irrelevant → reject + fallback  
- [ ] Stored question documents include skill/goal/difficulty/evidence fields  
- [ ] No protected-attribute question appears in approved fixture set  
- [ ] Validation failure does not crash the live session  

---

### PBI-C3 — Evidence-based scoring correctness (3 SP)

**Title:** `Evidence-only scoring with not_assessed — no invented low scores`

**Description**  
Scoring pipeline: Answer → Evidence extraction → Validation → Score. “I owned it” without detail is not evidence. Missing evidence → `not_assessed` / `insufficient_evidence`, never a hallucinated low score. Human override with reason already exists in API — keep AI card immutable; store overrides separately.

**Tasks**
- Add/extend tests for ownership idioms without detail → not scored as strong evidence.  
- Ensure each competency score cites turn_ids / evidence_ids; missing → `not_assessed`.  
- Scorecard includes: missing evidence list, answer excerpts, suggested human follow-ups, assessment status.  
- Quality metrics (`not_assessed_rate`, etc.) always present on generated cards.

**Acceptance**
- [ ] “I owned it.” alone → insufficient / not_assessed (test)  
- [ ] Every numeric rating has evidence references  
- [ ] Missing evidence never becomes rating 1 by inference  
- [ ] Override requires reason; AI card unchanged; audit event stored  

---

### PBI-C4 — Recruiter scorecard UI + BFF review (4 SP)

**Title:** `Recruiter scorecard UI with approve and override`

**Description**  
Ship a minimal results page: competencies (must/nice), evidence demonstrated, missing evidence, excerpts, suggested follow-ups, status, approve or override with reason. Wire BFF `GET` scorecard + `POST` review (backend review route already exists).

**Tasks**
- Next.js page e.g. `/interviewer/results/[sessionId]` (or query-param session).  
- BFF: GET scorecard/transcript; POST review proxy with service token.  
- UI: must-have vs nice-to-have, evidence excerpts, missing evidence, follow-ups, human actions.  
- Copy: advisory only — not an automatic hire decision.  
- Frontend test with mocked APIs.

**Acceptance**
- [ ] After completed interview, recruiter opens scorecard without curl  
- [ ] Approve and override (with reason) both work and persist  
- [ ] Must/nice, evidence, missing, excerpts, follow-ups all visible  
- [ ] Banner: advisory assessment; final decision is human  

---

## 8. Ujwal Kulal — Lead / staging / validation (8 SP) · `ujwal.kulal@gisul.co.in`

### PBI-D1 — Staging runbook + Redis hot layer (3 SP)

**Title:** `Staging runbook and Redis brain hot-memory layer`

**Description**
Reproducible stack; Redis in staging for brain hot snapshots; start order; fail-closed secrets; prove context carries across turns/restart.

**Doc:** `docs/staging_runbook_redis_brain.md` (VM path `/home/voiceai-runner/voice-ai-platform`, restart continuity §4.5).

**Acceptance**
- [ ] Clean machine completes one interview from runbook
- [ ] Redis key observed (or written exception)
- [ ] Restart continuity proven
- [ ] Rollback documented

### PBI-D2 — M7 validation matrix (3 SP)

**Title:** `End-to-end validation matrix — roles and failure drills`

**Description**
Junior/Senior BE, sparse/final-year resume, same JD different experience, non-answers, TTS fail (no voice change), time boundary, scorecard review path (Akshay).

**Doc:** `docs/m7_validation_matrix.md`

**Acceptance**
- [ ] ≥6 scenarios recorded pass/fail with owners
- [ ] Demo script ≤10 min on green path

### PBI-D3 — Board hygiene, publication gates, UI research note (2 SP)

**Title:** `Sprint board hygiene, publication gates, and UI research note`

**Description**
Azure board daily; creator publication gates; one-page note for next-sprint UI redesign (create/schedule/attend/results) — no redesign build this sprint.

**Docs / code:** `docs/ui_redesign_research_note.md`; gates in `SetupForm` + `brain/definition_service.py`.

**Acceptance**
- [ ] Board accurate by day 10
- [ ] Incomplete setup cannot publish
- [ ] UI research note in `docs/`

---

## 9. Shared demo DoD (by 2026-09-30)

1. Create + schedule with JD must-haves visible  
2. Candidate interview: pinned voice, no echo chaos, opening cites materials  
3. Questions tagged to competencies; no protected/trivia fails  
4. Complete → recruiter opens **Akshay’s scorecard**  
5. Must-have missing → not_assessed; evidenced must-have scored with citations  
6. Human override with reason  
7. TTS failure drill does not change voice  

---

## 10. Calendar (2026-09-15 → 2026-09-30)

| Dates | Abhijeet | Aditya | Akshay | Ujwal (Lead) |
|-------|-----------|--------|--------|-------|
| **Sep 15–16** | Harness baseline | Opening spike | Must/nice + scorecard API shape | Staging + Redis; create Azure iteration |
| **Sep 17–19** | Echo hard gate | Opening + claims | Validation suite + scoring tests | PR review; M7 fixtures |
| **Sep 20–23** | Voice pin + preflight | Non-answer / grace / close | **Recruiter scorecard UI** | Matrix runs start |
| **Sep 24–26** | Speech blockers only | Intelligence blockers only | Scorecard polish | Integrated staging demos |
| **Sep 27–29** | Evidence pack + fixes | Evidence pack + fixes | Scorecard demo ready | Full M7 pass |
| **Sep 30** | Sprint review evidence | Sprint review evidence | Scorecard live demo | Azure close + next backlog |

---

## 11. How to push this into Azure DevOps (CLI — preferred)

**Project:** https://dev.azure.com/Gisul/AI-Interviewer  
**Lead:** **Ujwal** runs this (needs **Basic+**, not Stakeholder).

### One-time install

```powershell
# Install Azure CLI if missing: https://aka.ms/installazurecliwindows
winget install -e --id Microsoft.AzureCLI

# Restart PowerShell, then:
az extension add --name azure-devops --upgrade --yes
az login
az devops configure --defaults organization=https://dev.azure.com/Gisul project=AI-Interviewer
```

Create a PAT (Azure DevOps → User settings → Personal access tokens) with **Work Items (Read & write)** + **Project and Team (Read & write)**:

```powershell
$env:AZURE_DEVOPS_EXT_PAT = "<paste-PAT-here>"   # session only; never commit
# or: az devops login --organization https://dev.azure.com/Gisul
```

### Run the push script (emails already set)

1. Open `docs/azure_push_sprint.ps1` only if you need to verify assignees  
2. Emails are already set (`gisul.co.in`)  
3. Run:

```powershell
cd C:\Gisul\voice-ai-platform
Set-ExecutionPolicy -Scope Process Bypass
.\docs\azure_push_sprint.ps1
```

Creates: iteration `Sprint 2026-09-15` (Sep 15–30), 1 Epic (Assigned **Ujwal** Lead), 4 Features, 13 PBIs with parent links.  
Board: https://dev.azure.com/Gisul/AI-Interviewer/_sprints

### Manual CLI (minimal)

```powershell
az boards iteration project create `
  --org https://dev.azure.com/Gisul `
  --project AI-Interviewer `
  --name "Sprint 2026-09-15" `
  --start-date 2026-09-15 `
  --finish-date 2026-09-30

az boards work-item create `
  --org https://dev.azure.com/Gisul `
  --project AI-Interviewer `
  --type Epic `
  --title "AI Interviewer production readiness — voice, live intelligence, structured scoring" `
  --description "Lead: Ujwal Kulal. Sprint 2026-09-15 to 2026-09-30." `
  --assigned-to "ujwal.kulal@gisul.co.in" `
  --iteration "AI-Interviewer\Sprint 2026-09-15"
```

Docs: [az boards work-item create](https://learn.microsoft.com/en-us/cli/azure/boards/work-item), [iterations](https://learn.microsoft.com/en-us/azure/devops/organizations/settings/set-iteration-paths-sprints?view=azure-devops).

### UI fallback

1. Project settings → Iterations → add `Sprint 2026-09-15` (2026-09-15 → 2026-09-30) → assign to team  
2. Create Epic (assign **Ujwal**) + 4 Features → parent-link to Epic  
3. Create 13 PBIs from §13; Iteration = `AI-Interviewer\Sprint 2026-09-15`; assign owners; Ujwal owns all Lead/ops items  
4. Boards → Sprints → pull PBIs in; capacity Abhijeet 13 / Aditya 13 / Akshay 13 / Ujwal 8  

Optional CSV: `docs/azure_sprint_work_items.csv`

---

## 12. Out of scope

- Full create/schedule/attend visual redesign (research note only)  
- OCR scanned PDFs  
- Full blueprint editor  
- Optional “objective 10/10” productization  
- Domain topics in system prompt  
- Production self-hosted model cutover  

---

## 13. Azure work-item titles (all)

| Assignee | Title | SP |
|----------|-------|----|
| Abhijeet | Latency and transcript quality measurement harness | 3 |
| Abhijeet | Hard echo and barge-in gate while agent is speaking | 5 |
| Abhijeet | Session-pinned TTS voice with preflight — no mid-session voice change | 5 |
| Aditya | JD and resume-aware interview opening | 5 |
| Aditya | Live resume claims, experience framing, and JD-based project ranking | 5 |
| Aditya | Non-answer ladder, time-boundary grace, closing, and anti-trivia | 3 |
| Akshay | Must-have vs nice-to-have competencies end-to-end | 3 |
| Akshay | Question validation — skill, goal, difficulty, and evidence criteria | 3 |
| Akshay | Evidence-only scoring with not_assessed — no invented low scores | 3 |
| Akshay | Recruiter scorecard UI with approve and override | 4 |
| Ujwal (Lead) | Staging runbook and Redis brain hot-memory layer | 3 |
| Ujwal (Lead) | End-to-end validation matrix — roles and failure drills | 3 |
| Ujwal (Lead) | Sprint board hygiene, publication gates, and UI research note | 2 |

---

## 14. Sources

- Azure project: https://dev.azure.com/Gisul/AI-Interviewer  
- Structured interviewing product brief (Akshay track)  
- Plan: `docs/ai_interviewer_brain_end_to_end_plan.md`  
- Code: compiler weights, `validator.py`, `scoring.py`, scorecard review API, missing results UI  
