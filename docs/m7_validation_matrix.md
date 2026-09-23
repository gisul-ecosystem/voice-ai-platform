# M7 validation matrix — roles and failure drills

Azure: User Story **2095** / Task **2082** (Ujwal Lead).

Purpose: record ≥6 staging scenarios with pass/fail, owner, and notes before demo.
Demo script target: ≤10 minutes on the green path.

Environment: `https://interviewer-dev.gisul.ai` (WireGuard) · Redis proof: `docs/staging_runbook_redis_brain.md`.

---

## How to run

1. Confirm Redis `PONG` and `brain_redis_connected` (Ujwal).
2. Stop local `aaptor` workers so staging `aaptor-staging` owns rooms.
3. For each row: schedule → attend → note result → fill Status / Evidence.
4. Attach session_id / screenshot / log snippet in Evidence (no secrets/PII beyond test fixtures).

Status values: `Pass` · `Fail` · `Blocked` · `Not run`

---

## Matrix

| # | Scenario | Owner | Priority | Status | Evidence / notes |
|---|----------|-------|----------|--------|------------------|
| 1 | **Junior BE** — light JD + early-career resume; opening + 3 turns coherent | Aditya + Ujwal | P0 | Pass | Fixture: `tests/test_opening_claims.py` (junior profile + claim cite); flow harness `test_harness/debug_flow_jd_resume.py` + `tests/test_flow_structure_debug.py` (2026-09-22) |
| 2 | **Senior BE** — deeper JD; probes stay applied (not trivia) | Aditya | P0 | Pass | Fixture: `tests/test_pbi_b3_ladder_grace.py` anti-trivia + ownership probe path; JD/resume harness targets `establish_ownership` (2026-09-22) |
| 3 | **Same JD, different experience** — mid vs senior resume; bar fixed, framing changes | Aditya | P1 | Pass | `test_same_jd_different_experience_keeps_job_bar` in `tests/test_opening_claims.py` |
| 4 | **Sparse / final-year resume** — still interviews; no invented claims | Aditya | P1 | Not run | Needs live sparse-resume invite on staging |
| 5 | **Non-answer ladder** — refuse → clarify → confirm continue → close | Aditya | P0 | Pass | `tests/test_pbi_b3_ladder_grace.py` (4-unusable close + closing message) |
| 6 | **TTS fail drill** — pause/end; **voice_id never switches** mid-session | Abhijeet | P0 | Not run | Owner lane; unit: `tests/test_tts_voice_policy.py` exists — live drill pending |
| 7 | **Echo / barge-in** — while AI speaks, no agent-echo as candidate turns | Abhijeet | P0 | Not run | Owner lane; unit: `tests/test_echo_not_persisted.py` — live laptop drill pending |
| 8 | **Time boundary + grace** — soft warn then structured close | Aditya | P1 | Pass | `test_soft_end_grace_offers_final_then_target_closes` in `tests/test_pbi_b3_ladder_grace.py` |
| 9 | **Scorecard path** — complete → AI scorecard → recruiter review/override | Akshay | P0 | Not run | Owner lane (UI); API generate exists |
| 10 | **Redis restart continuity** — key survives API/worker restart | Ujwal | P0 | Pass | 2026-09-22 staging: `redis-cli PONG`; seeded `interview:brain:m7_proof_20260922`; after `restart backend-api voice-agent` EXISTS=1 payload unchanged; stack healthy; tag `ebc7f23c2de56ac097b0ec7412a42c1e5a315424` |
| 11 | **Must-have missing → not_assessed** (no invented low score) | Akshay | P1 | Not run | Owner lane |
| 12 | **Publication gate** — incomplete setup cannot schedule/publish | Ujwal | P1 | Pass | `tests/test_brain_definitions.py::test_publish_and_store_blocks_incomplete_setup` + `tests/test_interview_brain_contracts.py` (12 passed 2026-09-22) |

**Acceptance for 2095:** at least scenarios **1, 2, 5, 6, 9, 10** recorded Pass (or Fail with owner + fix ticket). Demo script below stays green.

**Progress (2026-09-22):** Pass on **1, 2, 3, 5, 8, 10, 12** (7 scenarios). Still need owner sign-off on **6** (TTS) and **9** (scorecard UI) for full 2095 acceptance set.

---

## Demo script (≤10 min)

1. Create interview with JD must-haves + candidate (30s).  
2. Open invite → consent → live: pinned voice, no echo mess, opening cites JD/resume (4 min).  
3. Answer 2–3 turns; one follow-up that needs prior context (2 min).  
4. Complete → open scorecard → show must/nice + review (2 min).  
5. Optional: show Redis `EXISTS interview:brain:{session_id}` (30s).

---

## Sign-off

| Field | Value |
|-------|--------|
| Date | 2026-09-22 |
| Operator | Lead + Live intelligence lane |
| Image tag / SHA | `ebc7f23c2de56ac097b0ec7412a42c1e5a315424` (staging `.last-successful-tag`) |
| WireGuard / URL | interviewer-dev.gisul.ai |
| Pass count / total run | 7 / 12 (7 Pass, 5 Not run) |
| Blockers filed | #6 TTS live drill (Abhijeet); #9 scorecard UI (Akshay); #4/#7/#11 pending owners |

When acceptance rows **1, 2, 5, 6, 9, 10** pass → close Azure **2095** / **2082**.
