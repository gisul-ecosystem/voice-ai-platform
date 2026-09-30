---
kind: configuration_system
name: Environment-Driven Configuration Across Services
category: configuration_system
scope:
    - '**'
source_files:
    - services/voice-agent/clients/settings.py
    - services/backend-api/main.py
    - apps/voice-frontend/.env.example
    - services/backend-api/.env.example
    - services/voice-agent/.env.example
    - deploy/compose.staging.yml
    - apps/voice-frontend/lib/products.ts
---

## Approach

The monorepo uses a flat, environment-variable-driven configuration model with no centralized config framework. Each service loads its own `.env` via `python-dotenv.load_dotenv()` (Python services) or reads `process.env` directly (Next.js API routes). There is no schema validation library, no YAML/TOML/JSON config files consumed at runtime, and no feature-flag system — configuration is purely key-value pairs in `.env`, `env_file` directives in Docker Compose, and process environment variables.

## Key Files

- `services/voice-agent/clients/settings.py` — single source of truth for voice-agent HTTP client settings; defines typed helpers `_int`, `_float`, `_livekit_url` and exposes module-level constants (`LLM_PROVIDER`, `TTS_PROVIDER`, `STT_PROVIDER`, provider-specific keys/base URLs, timeouts, retry policy).
- `services/backend-api/main.py` — FastAPI entrypoint that calls `validate_startup_configuration()` to enforce required env vars when `APP_ENV` is `production` or `staging`; also wires CORS origins from `TEST_FRONTEND_ORIGINS`.
- `apps/voice-frontend/.env.example` — documents server-only vs browser-exposed (`NEXT_PUBLIC_`) variables; explicitly warns "Never expose this as NEXT_PUBLIC_*".
- `services/backend-api/.env.example` / `services/voice-agent/.env.example` — per-service variable inventories covering LiveKit, LLM/STT/TTS providers, Redis, retention policies, and product provider policies.
- `deploy/compose.staging.yml` — deployment-time configuration: `env_file` mounts secrets from `/etc/voice-ai-platform/*.env`, `environment:` overrides compose defaults with `${VAR:-default}` syntax, and healthchecks validate connectivity.
- `apps/voice-frontend/lib/products.ts` — compile-time product registry (not env-driven); only `interviewer` product exists today.

## Architecture & Conventions

1. **Per-service `.env` + `.env.example`**: Every Python service (`backend-api`, `voice-agent`, `context-engine`, `model-serving/stt`, `model-serving/tts`) ships a `.env.example` documenting all supported variables. Actual values live in per-deployment files mounted by Compose (`/etc/voice-ai-platform/backend-api.env`, `voice-agent.env`, `mongo.env`, `frontend.env`).

2. **Provider selection via string env vars**: LLM/STT/TTS backends are selected by `*_PROVIDER` env vars (`self_hosted`, `openai`, `sarvam`, `elevenlabs`, `deepgram`). The voice-agent's `settings.py` defaults each to `self_hosted` when unset, allowing local dev without provider keys. Provider-specific credentials follow naming conventions like `OPENAI_API_KEY`/`OPENAI_BASE_URL`, `ELEVENLABS_API_KEY`/`ELEVENLABS_BASE_URL`, `DEEPGRAM_API_KEY`/`DEEPGRAM_BASE_URL`, `SARVAM_API_KEY`/`SARVAM_STT_BASE_URL`.

3. **LiveKit URL aliasing**: `LIVEKIT_URL`, `LIVEKIT_WS_URL`, and `LIVEKIT_SERVER_URL` are treated as aliases; `_livekit_url()` returns the first non-empty one and strips trailing slashes. The value is then written back into `os.environ["LIVEKIT_URL"]` so downstream `livekit-agents` CLI code sees it.

4. **Startup validation gated by `APP_ENV`**: `main.validate_startup_configuration()` only enforces required variables when `APP_ENV` ∈ `{production, staging}`. In development mode missing DB connections fall back to in-memory storage (`set_fallback_mode(True)`), while production raises on startup failure.

5. **Weak-key guard for LiveKit**: Production/staging rejects placeholder keys (`devkey`, `dev`, `test`, `changeme`) unless `LIVEKIT_ALLOW_WEAK_API_KEY=true` is set — used intentionally in staging to keep shared keys working.

6. **Timeouts and retries as numeric env vars**: All inter-service timeouts use `*_TIMEOUT_SECONDS` env vars (`LLM_TIMEOUT_SECONDS`, `STT_TIMEOUT_SECONDS`, `TTS_TIMEOUT_SECONDS`, `BACKEND_TIMEOUT_SECONDS`, `CONTEXT_ENGINE_TIMEOUT_SECONDS`, `HTTP_CONNECT_TIMEOUT_SECONDS`). Retry attempts are clamped to `[1, 5]` via `max(1, min(_int(...), 5))`.

7. **Frontend separation of server vs client env**: Next.js API routes read `process.env.BACKEND_API_URL` and `process.env.BACKEND_SERVICE_TOKEN` directly (server-only). Browser-facing config uses `NEXT_PUBLIC_LIVEKIT_URL`. The `.env.example` comment enforces the rule: "Server-only FastAPI origin. Never expose this as NEXT_PUBLIC_*."

8. **Compose env precedence**: Deployment uses `env_file` for secrets and `environment:` for composable defaults via `${VAR:-default}` substitution. Service names (`aaptor-local`, `aaptor-staging`) are passed as `LIVEKIT_AGENT_NAME` / `INTERVIEWER_AGENT_NAME` to isolate workers across environments.

9. **Product-level provider policies**: Backend supports per-product provider overrides via `INTERVIEWER_LLM_PROVIDER`, `INTERVIEWER_STT_PROVIDER`, `INTERVIEWER_TTS_PROVIDER` (and `CUSTOMER_SUPPORT_*` variants), resolved at runtime and sent to the worker as room metadata.

## Conventions & Constraints

- **No schema validation**: Variables are parsed ad-hoc with `os.getenv(name, default)` and manual type coercion (`_int`, `_float`, boolean parsing via `in {"1", "true", "yes"}`). Invalid types raise `ValueError` at import/startup time rather than being validated against a schema.
- **Required variables are declared in code, not a schema**: `validate_startup_configuration()` in `main.py` lists required keys (`MONGO_URL`, `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`, `BACKEND_SERVICE_TOKEN`, `VOICE_AGENT_SERVICE_TOKEN`, `INTERVIEW_INVITATION_SECRET`, plus `OPENAI_API_KEY` when `LLM_PROVIDER=openai|openai_api|api`). Missing keys raise `RuntimeError("Missing required backend-api settings: ...")`.
- **Boolean env vars are case-insensitive**: Parsed as `value.strip().lower() in {"1", "true", "yes"}` (used for `TTS_PIN_VOICE`, `ELEVENLABS_USE_SPEAKER_BOOST`, `LIVEKIT_ALLOW_WEAK_API_KEY`).
- **URL env vars are normalized**: All URL env vars call `.rstrip("/")` before use to avoid double-slash joins.
- **Defaults are explicit per service**: `settings.py` comments state "Optional provider names and keys. Unset = today's self-hosted URL path. Not listed in .env.example so existing deployments keep the same defaults." — meaning `.env.example` is not exhaustive; some vars have sensible defaults in code.
- **Secrets never baked into images**: Compose mounts secret files from host paths (`/etc/voice-ai-platform/*.env`); no secrets appear in `compose.staging.yml` itself except via `${VAR:-default}` placeholders.
- **No feature flags or remote config**: Configuration is entirely static at process start; there is no hot-reload, no remote config server, and no toggle mechanism beyond changing env vars and restarting.