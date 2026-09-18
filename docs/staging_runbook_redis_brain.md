# Staging runbook — interview stack + Redis brain hot memory

Azure: User Story **2092** / Task **2081** (Ujwal Lead).

Goal: one person can bring staging up from secrets + Compose, run one full interview, and **prove** the hot brain key exists in Redis (or record a written exception).

Related: `deploy/README.md`, `deploy/compose.staging.yml`, `services/backend-api/db/redis_brain.py`.

---

## 1. Architecture (staging)

Start order (Compose `depends_on` already enforces health):

1. **mongo** — durable interview / definition / transcript truth  
2. **redis** — hot brain snapshots (`interview:brain:{session_id}`)  
3. **context-engine**  
4. **backend-api** — requires mongo + redis + context-engine healthy  
5. **voice-agent** — requires backend healthy  
6. **frontend** — requires backend healthy  
7. **gateway (Caddy)** — HTTPS edge  

Browser: `https://interviewer-dev.gisul.ai` on WireGuard (see `deploy/README.md`).

Memory layers:

| Layer | Where | Role |
|-------|--------|------|
| 1 | Worker RAM | Live turn speed |
| 2 | Redis | Hot session brain (this runbook) |
| 3 | Mongo | Durable truth |

Key format: `interview:brain:{session_id}`  
TTL: `INTERVIEW_BRAIN_REDIS_TTL_SECONDS` (default **21600** = 6h).

---

## 2. Fail-closed secrets (do not skip)

Secrets live **only** on the VM (never in git):

| File | Mode |
|------|------|
| `/etc/voice-ai-platform/` directory | `0750`, owner `root:voiceai-runner` |
| `backend-api.env` | `0640` |
| `voice-agent.env` | `0640` |
| `frontend.env` | `0640` |
| `mongo.env` | `0640` |

Required relationships:

- Frontend + backend share `BACKEND_SERVICE_TOKEN`
- Worker + backend share `VOICE_AGENT_SERVICE_TOKEN`
- Backend + worker share LiveKit credentials
- Provider keys as required by policy (OpenAI / Sarvam / ElevenLabs, etc.)

**Fail-closed rules for staging:**

- Do **not** start an interview demo if any of the above tokens/keys are empty.
- Do **not** commit or paste secrets into chat, PRs, or Azure work items.
- Prefer `APP_ENV=production` on staging Compose (already set for API/worker).
- If Redis is intentionally disabled, write an **exception** in the evidence section below (product accepts memory fallback in local/dev only; staging should use Redis).

Optional override in `backend-api.env` (Compose defaults to in-network Redis):

```bash
REDIS_URL=redis://redis:6379/0
INTERVIEW_BRAIN_REDIS_TTL_SECONDS=21600
```

---

## 3. Bring stack up

On the staging VM (paths match `deploy/README.md`):

```bash
cd "$HOME/voice-ai-platform"
docker compose -f compose.staging.yml ps
docker compose -f compose.staging.yml up -d
docker compose -f compose.staging.yml ps
```

Expect **redis** and **mongo** healthy before **backend-api**.

Logs:

```bash
docker compose -f compose.staging.yml logs --since=10m redis backend-api
```

Look for backend log event `brain_redis_connected`.  
If you see `brain_redis_unavailable` / `brain_redis_write_failed`, fix `REDIS_URL` / Redis health before claiming acceptance.

Redeploy a known SHA (rollback-friendly):

```bash
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io --username USER --password-stdin
"$HOME/voice-ai-platform/deploy.sh" ghcr.io/gisul-ecosystem COMMIT_SHA
docker logout ghcr.io
```

Last healthy tag: `$HOME/voice-ai-platform/.last-successful-tag`.

---

## 4. Prove Redis hot brain (acceptance)

### 4.1 Ping Redis

```bash
docker compose -f "$HOME/voice-ai-platform/compose.staging.yml" exec redis redis-cli ping
# expect: PONG
```

### 4.2 Run one interview

1. Open `https://interviewer-dev.gisul.ai` (WireGuard).  
2. Create/publish (or use existing) role interview; open candidate link.  
3. Enter name, upload CV, start live interview; complete at least **2–3 turns**.  
4. Note `session_id` from UI/network/logs (backend or worker).

### 4.3 Observe the key

While the session is live (or within TTL):

```bash
SESSION_ID="paste_session_id_here"
docker compose -f "$HOME/voice-ai-platform/compose.staging.yml" exec redis redis-cli EXISTS "interview:brain:${SESSION_ID}"
docker compose -f "$HOME/voice-ai-platform/compose.staging.yml" exec redis redis-cli GET "interview:brain:${SESSION_ID}" | head -c 400
docker compose -f "$HOME/voice-ai-platform/compose.staging.yml" exec redis redis-cli TTL "interview:brain:${SESSION_ID}"
```

**Pass:** `EXISTS` = `1`, payload JSON includes matching `session_id`, TTL &gt; 0.

**Exception (document if used):** Redis deliberately off; hot path returned `memory` only — **not** acceptable for staging sign-off of 2092 unless Lead + stakeholder agree in writing.

### 4.4 Context carry smoke

During the same interview, ask a follow-up that depends on an earlier answer.  
Pass if the agent continues coherently (qualitative). Optional: compare Redis snapshot before/after a turn (JSON grows / fields update).

---

## 5. Rollback

1. Note current tag: `cat "$HOME/voice-ai-platform/.last-successful-tag"`.  
2. Redeploy previous known-good SHA via `deploy.sh` (section 3).  
3. Confirm `docker compose ... ps` healthy; re-check `redis-cli ping`.  
4. If Redis volume corruption suspected: stop API, `docker compose ... stop redis`, restore from backup or recreate volume **only** after Mongo durable data is verified (Redis is hot cache, not source of truth).

---

## 6. Evidence checklist (paste into Azure 2092 / 2081)

- [ ] Date / operator  
- [ ] Image tag / commit SHA  
- [ ] `redis-cli ping` = PONG  
- [ ] Backend log shows `brain_redis_connected`  
- [ ] One full interview completed from this runbook  
- [ ] `EXISTS interview:brain:{session_id}` = 1 (or written exception)  
- [ ] Rollback path exercised or documented  

When all boxes pass → move story **2092** and task **2081** to **Closed**.

---

## 7. Local/dev note (not staging acceptance)

Unset `REDIS_URL` → process-memory fallback (`put_hot_snapshot` returns `memory`).  
Unit coverage: `services/backend-api/tests/test_brain_state_store.py`.  
Local compose Redis is optional; staging Compose **includes** Redis as of this runbook.
