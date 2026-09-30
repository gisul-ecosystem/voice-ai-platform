# SLO baseline record — AI Interviewer

**Date:** 2026-09-22  
**Operator:** Lead lane (production build)  
**Source:** [docs/interviewer_slos.md](interviewer_slos.md)  
**Harness:** `services/voice-agent/test_harness/slo_baseline.py`

## Reproduce (no provider keys)

```bash
cd services/voice-agent
set PYTHONPATH=.
python test_harness/slo_baseline.py
python -m pytest tests/test_latency_budget.py -q
```

## First-pass fixture baseline (2026-09-22)

Harness output (`python test_harness/slo_baseline.py`):

| Metric | Target | Measured | Result |
|--------|--------|----------|--------|
| Composed speech-end→first audio (budget math) | p50 ≤ 1200 ms; p95 ≤ 1500 ms | 1150 ms | Pass |
| Prompt size (structured turn) | ≤ 8500 chars | 6371 chars | Pass |
| Fixture sample summary p50 / p95 | ≤ 1200 / ≤ 1500 | 1125.0 / 1347.5 ms | Pass |

Budgets in code: `products/interviewer/latency.py`  
(`SPEECH_END_TO_FIRST_AUDIO_P50_MS=1200`, `P95=1500`).

## Live staging samples

| Field | Value |
|-------|--------|
| Environment | interviewer-dev.gisul.ai |
| Image / SHA | fill after live invite |
| Sample count | 0 (pending live `stage_latency` scrape) |
| p50 / p95 ms | — |
| Meets launch p95 ≤ 1500 | Pending |

**How to fill:** run one staging invite; collect worker `stage_latency` / speech-end→audio timestamps (no PII); append `samples_ms` and re-run `summarize_first_audio` via the harness or pytest.

## Related gates (not latency)

| Gate | How checked |
|------|-------------|
| Session prep / join | Staging compose healthy + invite join |
| Durable completion | Scorecard API after complete |
| Redis hot brain | `docs/staging_runbook_redis_brain.md` + M7 #10 |
