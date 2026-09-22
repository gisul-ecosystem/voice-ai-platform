# UI redesign research note (next sprint — no build this sprint)

Azure: User Story **2096** / Task **2083** (Ujwal Lead).

Scope: one-page note only. **Do not** redesign create / schedule / attend / results in this sprint.

---

## Current surfaces

| Journey | Today | Pain |
|---------|--------|------|
| **Create / schedule** | `SetupForm` 3 steps + review | Dense; competencies as comma text; no explicit “publication ready” checklist UI |
| **Attend** | Consent → prejoin → LiveKit room + transcript | Echo/order polish in flight; no strong session status strip |
| **Results** | Scorecard **API** exists; **UI missing** (Akshay P0) | Recruiters use curl/API — blocks demo story |
| **Ops** | Staging via WireGuard + Compose | Not a product UI concern |

---

## Next-sprint redesign goals (proposal)

1. **Creator** — publication readiness checklist (JD approved, ≥1 competency, candidate, time) before Schedule; must/nice chips not free-text only.  
2. **Attend** — calm single-column live view; transcript sticky; clear “AI speaking / listening”.  
3. **Results** — scorecard first screen after complete (Akshay); approve/override with reason; evidence excerpts.  
4. **Shared** — one product type scale, fewer cards, no dashboard chrome on create/attend.

Out of scope still: full blueprint editor, OCR, marketing landing redesign.

---

## Dependencies before redesign build

- Akshay scorecard UI (this sprint) — redesign iterates on that, does not replace it mid-sprint.  
- Aditya opening + Abhijeet voice pin — demo quality before visual polish.  
- Publication gates (this sprint) — incomplete setup already blocked in product path.

---

## Decision

| Item | Choice |
|------|--------|
| This sprint | Gates + scorecard UI + voice/intelligence P0 only |
| Next sprint | Visual redesign of create → attend → results using this note |
| Owner for kickoff | Ujwal (brief) + frontend assignee TBD |
