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
| 1 | **Junior BE** — light JD + early-career resume; opening + 3 turns coherent | Aditya + Ujwal | P0 | Not run | |
| 2 | **Senior BE** — deeper JD; probes stay applied (not trivia) | Aditya | P0 | Not run | |
| 3 | **Same JD, different experience** — mid vs senior resume; bar fixed, framing changes | Aditya | P1 | Not run | |
| 4 | **Sparse / final-year resume** — still interviews; no invented claims | Aditya | P1 | Not run | |
| 5 | **Non-answer ladder** — refuse → clarify → confirm continue → close | Aditya | P0 | Not run | |
| 6 | **TTS fail drill** — pause/end; **voice_id never switches** mid-session | Abhijeet | P0 | Not run | |
| 7 | **Echo / barge-in** — while AI speaks, no agent-echo as candidate turns | Abhijeet | P0 | Not run | |
| 8 | **Time boundary + grace** — soft warn then structured close | Aditya | P1 | Not run | |
| 9 | **Scorecard path** — complete → AI scorecard → recruiter review/override | Akshay | P0 | Not run | |
| 10 | **Redis restart continuity** — key survives API/worker restart | Ujwal | P0 | Not run | See runbook §4.5 |
| 11 | **Must-have missing → not_assessed** (no invented low score) | Akshay | P1 | Not run | |
| 12 | **Publication gate** — incomplete setup cannot schedule/publish | Ujwal | P1 | Not run | Empty JD / no competencies blocked |

**Acceptance for 2095:** at least scenarios **1, 2, 5, 6, 9, 10** recorded Pass (or Fail with owner + fix ticket). Demo script below stays green.

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
| Date | |
| Operator | Ujwal Kulal |
| Image tag / SHA | |
| WireGuard / URL | interviewer-dev.gisul.ai |
| Pass count / total run | |
| Blockers filed | |

When acceptance rows pass → close Azure **2095** / **2082**.
