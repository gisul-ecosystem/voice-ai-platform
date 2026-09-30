---
kind: error_handling
name: Error Handling Across Backend API, Voice Agent, and Frontend
category: error_handling
scope:
    - '**'
source_files:
    - services/voice-agent/clients/errors.py
    - services/voice-agent/clients/tts/resilient.py
    - services/voice-agent/products/interviewer/worker.py
    - services/backend-api/main.py
    - services/backend-api/routers/admin_candidates.py
    - services/backend-api/routers/brain_state.py
    - services/backend-api/routers/brain_intelligence.py
    - services/backend-api/brain/documents.py
    - services/backend-api/db/interviews.py
    - apps/voice-frontend/app/interviewer/attend/error.tsx
---

## Overview

The monorepo uses three distinct error-handling strategies depending on layer:

- **Backend API (FastAPI/Python)**: domain-specific `Exception` subclasses plus FastAPI's `HTTPException` for HTTP-layer errors; a global HTTP middleware logs every request/response with correlation IDs.
- **Voice Agent (Python)**: custom exception classes (`ServiceUnavailableError`, `ProviderConfigError`, `InterviewPlanUnavailableError`) propagate provider failures upward; resilience is implemented via wrapper classes (e.g. `ResilientTts`) that catch these exceptions and retry/failover.
- **Frontend (Next.js App Router)**: per-route `error.tsx` files render user-facing messages; client-side errors bubble through React's error boundary protocol.

There is no single shared error SDK across services — each Python service defines its own types, and the Next.js app handles errors locally.

## Backend API (`services/backend-api`)

### Domain exceptions

| Exception | Location | Purpose |
|---|---|---|
| `DocumentIngestError(ValueError)` | `brain/documents.py` | Document ingestion/validation failures |
| `ExternalInterviewConflictError(Exception)` | `db/interviews.py` | Conflict when an interview already exists externally |
| `InterviewPlanUnavailableError(RuntimeError)` | `products/interviewer/worker.py` | Missing or disallowed interview plan definition |

These are raised inside business logic and caught by routers, which translate them into `HTTPException`s.

### HTTP error surface

Routers raise `fastapi.HTTPException` directly with explicit `status_code` and human-readable `detail` strings. Observed status codes:

- `404` — resource not found (e.g. candidate, interview definition, interview context)
- `409` — conflict (question/answer/evidence already has different data)
- `422` — validation / malformed input (session_id mismatch, missing fields, invalid kind)
- `503` — downstream dependency unavailable (Redis brain state store)
- `204` — successful mutation with no body (used via `Response(status_code=204)`)

Validation errors from Pydantic models are re-raised as `HTTPException(422, detail=str(exc)) from exc` so the original traceback is preserved while returning a clean JSON error to callers.

### Startup and lifecycle errors

`main.validate_startup_configuration()` raises `RuntimeError` if required environment variables are missing in production/staging. The `startup()` lifespan hook wraps DB connectivity in try/except: on failure it logs `startup_failed` and either re-raises (production/staging) or falls back to an in-memory store via `set_fallback_mode(True)` (development).

### Global logging middleware

`main.log_requests` is registered as an `@app.middleware("http")`. It:

1. Extracts `x-correlation-id` from the request header and sets it via `observability.set_correlation_id`.
2. Calls `call_next(request)`.
3. Writes back the correlation ID to the response header.
4. Logs `http_request` with method, path, `status`, latency_ms, and correlation_id.

This is the only centralized error-adjacent middleware; there is no global exception handler overriding FastAPI's default JSON error responses.

## Voice Agent (`services/voice-agent`)

### Custom exception hierarchy

Defined in `clients/errors.py`:

```python
class ServiceUnavailableError(Exception):
    """Raised when an STT/TTS/LLM (or backend) HTTP call fails after retries."""

class ProviderConfigError(Exception):
    """Raised at session start when a provider is selected without a usable API key."""
```

Both carry structured attributes (`service`, `url`, `provider`) beyond the message, enabling observability and routing decisions.

### Resilience wrappers

`clients/tts/resilient.ResilientTts` is the canonical pattern: it wraps a primary TTS provider and an optional fallback. Its `_should_failover` function inspects the exception text for tokens like `401`, `402`, `403`, `429`, `payment`, `unauthorized`, `quota`, `paid_plan` to decide whether to switch providers. When `pin_voice=True`, it retries the primary once before giving up; otherwise it attempts the fallback.

The same class mirrors `synthesize` and `stream_synthesize` so callers can use it transparently.

### Worker-level handling

`products/interviewer/worker.py` catches `ServiceUnavailableError` around provider calls and converts them to `InterviewPlanUnavailableError` (a `RuntimeError` subclass) when the root cause is a missing/disallowed interview plan. This separates transient provider outages from configuration errors.

## Frontend (`apps/voice-frontend`)

Next.js App Router convention is used: route directories under `app/` may include an `error.tsx` file. The only one present is `app/interviewer/attend/error.tsx`, which renders a card with role `alert`, displays `error.message` when available, and offers a "Retry interview" button wired to React's `reset()` callback plus a link back to `/interviewer`.

Other routes do not define dedicated error pages, so they fall back to Next.js defaults.

## Conventions observed

1. **Domain exceptions are plain `Exception` subclasses** (not wrapped in a common base), defined close to where they are raised, and documented with docstrings explaining their trigger condition.
2. **HTTP boundaries are explicit**: Python domain exceptions are never returned directly to clients; routers convert them to `HTTPException` with a numeric status code and a short `detail` string.
3. **Status codes are chosen semantically**, not uniformly: 404 for missing resources, 409 for optimistic-concurrency conflicts, 422 for validation/malformed input, 503 for downstream unavailability.
4. **Structured attributes on exceptions** (`service`, `url`, `provider`) are used to enrich logs rather than relying solely on the message.
5. **Failover is opt-in via wrapper classes** (`ResilientTts`) rather than implicit retry everywhere; the decision to fail over is based on keyword matching against the exception message.
6. **Startup validation fails fast** with `RuntimeError` in production/staging environments, and database connection failures are handled differently per environment (re-raise vs. in-memory fallback).
7. **Correlation IDs flow through requests** via a FastAPI HTTP middleware that injects `x-correlation-id` into both request context and response headers.
8. **Frontend errors follow Next.js conventions** with per-route `error.tsx` components using React's error boundary contract (`error`, `reset`).

## Constraints enforced by the codebase

- Production/staging startup requires `MONGO_URL`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `BACKEND_SERVICE_TOKEN`, `VOICE_AGENT_SERVICE_TOKEN`, `INTERVIEW_INVITATION_SECRET`; if `LLM_PROVIDER` is `openai`/`openai_api`/`api`, `OPENAI_API_KEY` is also required — omission raises `RuntimeError` (`main.validate_startup_configuration`).
- `LIVEKIT_API_KEY` must not be a placeholder value (`devkey`, `dev`, `test`, `changeme`) unless `LIVEKIT_ALLOW_WEAK_API_KEY=true` — violation raises `RuntimeError`.
- Redis brain state endpoints return `503` when the store is unavailable, signaling a downstream dependency failure rather than masking it as a generic server error.