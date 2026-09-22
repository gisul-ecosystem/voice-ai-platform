# Azure sprint PBI mapping — Lead + Live intelligence

**Lane (this session):** Lead/M7 (Ujwal) + Live intelligence (Aditya)  
**Date:** 2026-09-22  
**Source plan:** Production-scale AI Interviewer build

Maps code and fixtures to Azure PBIs so we only land production-standard work (not ad-hoc patches).

---

## Live intelligence (Aditya)

| PBI | Acceptance theme | Code / fixtures | Status |
|-----|------------------|-----------------|--------|
| **B1** JD/resume-aware opening | Cite claim/JD when context exists; generic fallback without | `flow.py` opening path; `tests/test_opening_claims.py`; `tests/test_opening_cite_softcheck.py` | Done (tests) |
| **B2** Claims, framing, project ranking | Same JD / different experience; bar fixed | Policy + claims in brain/flow; opening/claims tests | Mostly done |
| **B3** Non-answer, grace, close, anti-trivia | 4-unusable close; grace; closing; anti-trivia | `policy.py` non-answer + soft end; `validator.py` trivia; `tests/test_pbi_b3_ladder_grace.py` | Done (tests) |
| **B3+** Structured follow-ups | Leading block; rewrite before silent fallback; dry-probe advance | `validator.py` `leading_question`; `flow.py` rewrite + `consecutive_dry_probes`; `policy.py` dry exhaust; `coverage.py` soft off-topic; `tests/test_flow_structure_debug.py`; `test_harness/debug_flow_jd_resume.py` | Done (this lane) |

## Lead / staging / validation (Ujwal)

| PBI | Acceptance theme | Code / docs | Status |
|-----|------------------|-------------|--------|
| **D1** Staging Redis runbook | PONG; key; restart continuity | `docs/staging_runbook_redis_brain.md`; `deploy/scripts/staging_redis_brain_proof.sh` | Prove on VM (M7 #10) |
| **D2** M7 matrix ≥6 scenarios | Pass/fail recorded | `docs/m7_validation_matrix.md` | Update with fixture + Redis evidence |
| **D3** Publication gates | Incomplete setup blocked | `brain/publish.py`; `SetupForm.tsx`; backend tests | Covered by unit tests (M7 #12) |

## Explicitly not this lane

| PBI | Owner | Notes |
|-----|--------|------|
| A1–A3 speech / echo / voice pin | Abhijeet | Voice pin shipped earlier; echo hard-gate + live latency samples remain |
| C1–C4 must/nice + scorecard UI | Akshay | API partial; recruiter UI out of scope here |

## Reproduce commands

```bash
cd services/voice-agent
set PYTHONPATH=.
python -m pytest tests/test_flow_structure_debug.py tests/test_pbi_b3_ladder_grace.py tests/test_opening_claims.py tests/test_opening_cite_softcheck.py tests/test_question_validator.py tests/test_interview_policy_flow.py -q
python test_harness/debug_flow_jd_resume.py
python test_harness/slo_baseline.py
```
