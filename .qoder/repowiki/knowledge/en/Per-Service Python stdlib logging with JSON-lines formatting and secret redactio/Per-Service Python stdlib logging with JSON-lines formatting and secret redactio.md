---
kind: logging_system
name: Per-Service Python stdlib logging with JSON-lines formatting and secret redaction
category: logging_system
scope:
    - '**'
source_files:
    - services/backend-api/logging_config.py
    - services/voice-agent/logging_config.py
    - services/context-engine/logging_config.py
    - services/backend-api/main.py
    - services/context-engine/app.py
    - services/voice-agent/aaptor_agent.py
    - services/voice-agent/racko_agent.py
---

## Approach

Every Python service in the monorepo uses the **Python standard library `logging` module** — no third-party logger framework (no structlog, loguru, or Sentry SDK). Each service ships its own `logging_config.py` that installs a single `StreamHandler(sys.stdout)` with a custom `JsonFormatter`, producing one JSON object per line so an external observability stack can scrape logs without rewriting call sites. The frontend (`apps/voice-frontend`) has no equivalent logging subsystem; it is a Next.js app.

## Key files

- `services/backend-api/logging_config.py` — JSON formatter + root setup for the FastAPI backend.
- `services/voice-agent/logging_config.py` — JSON formatter + root setup for the LiveKit agent processes (`aaptor_agent.py`, `racko_agent.py`).
- `services/context-engine/logging_config.py` — minimal JSON formatter for the context retrieval service.
- Entrypoints: `services/backend-api/main.py`, `services/context-engine/app.py`, `services/voice-agent/aaptor_agent.py`, `services/voice-agent/racko_agent.py` each import and call `configure_logging()` at process start.

## Architecture and conventions

### Per-service configuration
Each service owns its `logging_config.py`. There is no shared logging package under `packages/`; duplication is intentional so each process configures its own `service` field and log level.

### JSON-lines output
The custom `JsonFormatter.format` builds a dict with fixed fields:
- `ts` — UTC ISO timestamp derived from `record.created`.
- `level` — stringified level name.
- `logger` — `record.name`.
- `msg` — `record.getMessage()`.
- `exc_info` — serialized exception when present.
- `service` — hard-coded per service (`backend-api`, `voice-agent`, `context-engine`).
- Any extra keys attached via `extra={...}` on the log call are copied verbatim into the payload.

This makes structured fields opt-in at the call site rather than through a dedicated logger factory.

### Secret redaction
`backend-api` and `voice-agent` share an identical redaction strategy implemented by `_is_secret_field` / `redact_secrets`. Keys matching any of the exact names `api_key`, `apikey`, `authorization`, `openai_api_key`, `llm_api_key`, `stt_api_key`, `tts_api_key`, `api_key_override`, or ending with `_api_key` / `_apikey` are replaced with `"***"` recursively across nested dicts/lists. `context-engine`'s formatter does not apply this filter.

### Log levels
- Default level is read from the `LOG_LEVEL` environment variable, upper-cased, defaulting to `INFO`.
- Third-party loggers are explicitly suppressed: `httpx` and `httpcore` are set to `WARNING`; `uvicorn.access` is also downgraded in `backend-api`; `livekit` is left at `INFO` in `voice-agent`.

### Structured-field convention
Call sites attach event metadata via `extra={"event": "...", ...}`. Observed patterns include `event: startup`, `mongo_client_created`, `brain_redis_connected`, `mongo_ping_failed`, `room_metadata_invalid`, `emergency_llm_ok`, `session_start`, etc. The message itself is typically a short keyword string (e.g. `"startup"`, `"session_start"`) while richer context lives in `extra`.

### Rate-limiting loop-monitor noise
`voice-agent/logging_config.py` adds a `_RateLimitLoopMonitor(logging.Filter)` that suppresses repeated LiveKit warnings containing `event loop blocked` or `job executor is unresponsive`, emitting at most once per configurable interval (default 30s) and replacing large stack traces with `(rate-limited; see prior sample)` to avoid amplifying stalls caused by logging under a lock.

### Windows UTF-8 handling
The voice-agent formatter reconfigures `sys.stdout`/`sys.stderr` to UTF-8 with `errors="replace"` so non-ASCII STT transcripts do not crash the console writer.

## Conventions and constraints

1. **New services must ship their own `logging_config.py`** — there is no shared logger package; every service's entrypoint imports and calls `configure_logging()` before doing I/O.
2. **Log output is JSON-lines on stdout** — the formatter writes one `json.dumps(...)` per record; no file handlers are installed.
3. **Structured fields go through `extra=`** — business events use `logger.info("keyword", extra={"event": "...", ...})`; arbitrary key/value pairs become top-level JSON fields.
4. **Secrets are redacted automatically** in `backend-api` and `voice-agent` based on the `_SECRET_EXACT` set plus suffix heuristics (`*_api_key`, `*_apikey`); callers should not manually mask values passed as `extra`.
5. **`LOG_LEVEL` env var controls verbosity** — defaults to `INFO` if unset.
6. **Third-party loggers are muted** — `httpx`/`httpcore` at `WARNING`; `uvicorn.access` at `WARNING` (backend-api only).
7. **The `service` field is hard-coded per service** in the formatter and is the intended routing dimension for the observability stack.