# Briefing for leadership — AI Interviewer architecture & plan

**Use this when asked:** What is the architecture? What plan did you make after the feedback?

---

## 1. One-minute answer (say this first)

We built an **interview brain** on top of LiveKit voice.

- **Job description sets the bar** (must-have competencies).  
- **Resume only personalizes** questions — it does not lower the standard.  
- A **policy engine** controls what happens next (breadth → depth → close).  
- The **LLM only phrases** the question; it does not freely decide the interview.  
- Every answer is stored; scores are **evidence-linked** and **advisory** — humans decide hire/no-hire.  
- Memory is **3-layer**: worker RAM → Redis (hot) → Mongo (durable).  

This sprint (15–30 Sep) closes the remaining demo gaps: **stable voice**, **JD/resume-aware live talk**, **recruiter scorecard UI**, and **validation**.

---

## 2. Architecture (draw this on whiteboard / screen)

```text
Creator (setup JD + resume)
        │
        ▼
backend-api (FastAPI)  ←── source of truth
  • ingest PDF/DOCX
  • extract JD + resume
  • compile + publish immutable interview definition
  • schedule + invitation
  • transcript + brain snapshots + scorecard
        │
        ├── MongoDB (definitions, sessions, turns, scorecards)
        └── Redis (hot brain snapshot per session)
        │
        ▼
Candidate joins (invite link) → LiveKit room
        │
        ▼
voice-agent worker
  • Sarvam STT  →  OpenAI LLM  →  ElevenLabs TTS
  • loads published definition
  • policy: next action / depth / time / close
  • remembers what was asked and answered
        │
        ▼
completed → advisory scorecard → human review
```

**Trust rule:** Browser never sees provider API keys. Backend owns lifecycle. Worker only runs the live conversation.

**Why not a separate “context microservice”?**  
Brain lives in backend + worker today. Same monorepo can later serve Aaptor (interview) and Racko (support) as separate products — shared voice stack, separate product logic.

---

## 3. How we answered the earlier feedback

| Feedback | Our decision / design |
|----------|------------------------|
| Voice changing mid-demo | Pin one TTS voice per session; on failure pause/end — never silent switch (this sprint: Abhijeet) |
| Does context carry? | Yes — 3-layer memory (RAM → Redis → Mongo); prove on staging (Ujwal) |
| Resume known to AI | Extract + claims in context; opening must cite a claim (Aditya) |
| Final year / BCA–MCA vs same JD | Job **level** stays fixed; **framing** adapts to experience — bar not lowered |
| Memory of Q/A | Question ledger + turns + snapshots already designed and largely wired |
| 3–4 non-answers | Controlled clarify → close after threshold (Aditya) |
| 30 min still talking | Soft/hard end + short grace — finish cleanly, don’t hard-cut mid-answer |
| Scoring | Evidence only; missing → `not_assessed`; no invented low score (Akshay) |
| Proper ending | Structured closing like opening (Aditya) |
| No trivia / full-forms | Level-appropriate applied questions (Aditya) |
| Domain-neutral system prompt | No hardcoded “API/Kafka/sales” topics in the universal prompt — competencies come from JD |
| Creator structure | Mandatory fields before publish (role, JD, level, duration, competencies) |
| Human still decides | AI scorecard is advisory; recruiter approve/override (Akshay UI this sprint) |

---

## 4. What is already built vs this sprint

**Already built (core path works end-to-end):**  
Setup → ingest JD/resume → schedule → invite → live policy interview → full transcript → AI scorecard API.

**This sprint closes production/demo gaps (15–30 Sep):**

| Owner | Focus |
|-------|--------|
| **Ujwal (Lead)** | Staging + Redis, validation matrix, board, publication gates |
| **Abhijeet** | Speech quality, echo gate, pinned voice / TTS preflight |
| **Aditya** | JD/resume opening, claims, experience framing, non-answer/time/close |
| **Akshay** | Must/nice competencies, question validation, evidence scoring, **recruiter scorecard UI** |

Azure project: **AI-Interviewer** · Sprint **2026-09-15 → 2026-09-30**.

---

## 5. Product principles (if he asks “how should interviews work?”)

1. **JD defines assessment** — resume personalizes only.  
2. **Same competencies** for candidates for the same role — wording may differ.  
3. **Breadth before depth** — map background, then probe.  
4. **Policy controls flow** — LLM phrases, does not own progression.  
5. **Claims ≠ evidence** until explained in the interview.  
6. **Score only what was demonstrated** — else `not_assessed`.  
7. **AI is advisory** — human makes the hiring decision.  
8. **Published definition is immutable** — audit per candidate version.

---

## 6. Likely questions — short answers

**Q: Why LiveKit?**  
Real-time audio transport. Our worker does STT→LLM→TTS; LiveKit is the media plane only.

**Q: Where is intelligence stored?**  
Mongo = durable truth. Redis = fast session brain. Worker RAM = live turn speed.

**Q: Will students get easier interviews?**  
No. Same job bar. We only change how questions are framed to their experience.

**Q: Can it do non-tech roles?**  
Yes by design — system prompt is domain-neutral; competencies come from the JD (e.g. Sales Executive validation later).

**Q: When is it demo-ready?**  
Core path works now. By **30 Sep** we target: stable voice, resume-aware opening, recruiter scorecard UI, and a measured validation matrix.

**Q: What is out of scope this sprint?**  
Full page redesign, OCR for scanned PDFs, full blueprint editor, production self-hosted models cutover.

---

## 7. Closing line

“Architecture is decided and largely implemented. Feedback is mapped item-by-item into a timed sprint with clear owners. Next milestone is a clean, measured demo with pinned voice, JD-first scoring, and a human-reviewable scorecard.”

---

**Docs behind this brief**  
- `docs/ai_interviewer_production_architecture.md`  
- `docs/ai_interviewer_brain_end_to_end_plan.md`  
- `docs/azure_sprint_ai_interviewer_next.md`
