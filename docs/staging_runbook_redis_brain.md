# Staging runbook — interview stack + Redis brain hot memory

Azure: User Story **2092** / Task **2081** (Ujwal Lead).

Goal: one person can bring staging up from secrets + Compose, run one full interview, and **prove** the hot brain key exists in Redis across API/worker restart (or record a written exception).

Related: `deploy/README.md`, `deploy/compose.staging.yml`, `services/backend-api/db/redis_brain.py`.

---

## 0. VM paths (current staging)

Deployed checkout (not `$HOME` for `gisuladmin`):

```bash
APP=/home/voiceai-runner/voice-ai-platform
COMPOSE="sudo docker compose -f $APP/compose.staging.yml --project-directory $APP"
```

Use `$COMPOSE` in the commands below. `gisuladmin` needs passwordless sudo for Docker (already configured on the staging VM).

SSH (from a WireGuard-connected laptop):

```bash
ssh -i ~/.ssh/voice-ai-staging gisuladmin@10.110.50.10
```

Browser: `https://interviewer-dev.gisul.ai` on WireGuard.

---

## 1. Architecture (staging)

Start order (Compose `depends_on` already enforces health):

1. **mongo** — durable interview / definition / transcript truth  
2. **redis** — hot brain snapshots (`interview:brain:{session_id}`)  
3. **context-engine**  
4. **backend-api** — requires mongo + redis + context-engine healthy  
5. **voice-agent** — requires backend healthy (`LIVEKIT_AGENT_NAME=aaptor-staging`)  
6. **frontend** — requires backend healthy  
7. **gateway (Caddy)** — HTTPS edge  

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
- Stop local `voice-agent` on `aaptor` while testing staging, or keep staging on `aaptor-staging` only.

Optional override in `backend-api.env` (Compose defaults to in-network Redis):

```bash
REDIS_URL=redis://redis:6379/0
INTERVIEW_BRAIN_REDIS_TTL_SECONDS=21600
```

---

## 3. Bring stack up

```bash
APP=/home/voiceai-runner/voice-ai-platform
COMPOSE="sudo docker compose -f $APP/compose.staging.yml --project-directory $APP"

$COMPOSE ps
$COMPOSE up -d
$COMPOSE ps
```

Expect **redis** and **mongo** healthy before **backend-api**.

Logs:

```bash
$COMPOSE logs --since=10m redis backend-api
```

Look for backend log event `brain_redis_connected`.  
If you see `brain_redis_unavailable` / `brain_redis_write_failed`, fix `REDIS_URL` / Redis health before claiming acceptance.

Redeploy a known SHA (rollback-friendly):

```bash
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io --username USER --password-stdin
sudo "$APP/deploy.sh" ghcr.io/gisul-ecosystem COMMIT_SHA
docker logout ghcr.io
```

Last healthy tag: `$APP/.last-successful-tag`.

---

## 4. Prove Redis hot brain (acceptance)

Operator script on the VM (after 2–3 live turns):

```bash
APP=/home/voiceai-runner/voice-ai-platform
SESSION_ID="paste_session_id_here"
bash $APP/deploy/scripts/staging_redis_brain_proof.sh
PROVE_RESTART=1 SESSION_ID="$SESSION_ID" bash $APP/deploy/scripts/staging_redis_brain_proof.sh
```

### 4.1 Ping Redis

```bash
$COMPOSE exec -T redis redis-cli ping
# expect: PONG
# or: sudo docker exec voice-ai-platform-redis-1 redis-cli ping
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
$COMPOSE exec -T redis redis-cli EXISTS "interview:brain:${SESSION_ID}"
$COMPOSE exec -T redis redis-cli GET "interview:brain:${SESSION_ID}" | head -c 400
$COMPOSE exec -T redis redis-cli TTL "interview:brain:${SESSION_ID}"
```

**Pass:** `EXISTS` = `1`, payload JSON includes matching `session_id`, TTL &gt; 0.

**Exception (document if used):** Redis deliberately off; hot path returned `memory` only — **not** acceptable for staging sign-off of 2092 unless Lead + stakeholder agree in writing. Staging Compose sets `APP_ENV=production` and **refuses silent memory fallback** when `REDIS_URL` is set.

### 4.4 Context carry smoke

During the same interview, ask a follow-up that depends on an earlier answer.  
Pass if the agent continues coherently (qualitative). Optional: compare Redis snapshot before/after a turn (JSON grows / fields update).

### 4.5 Restart continuity (required for 2092 sign-off)

Hot Redis must survive **API/worker process restart** (RAM is wiped; Redis + Mongo keep state).

While the same `SESSION_ID` key still exists (`EXISTS` = 1):

```bash
$COMPOSE exec -T redis redis-cli GET "interview:brain:${SESSION_ID}" | head -c 200 > /tmp/brain_before.txt

# Restart API + worker only (do NOT recreate the redis volume)
$COMPOSE restart backend-api voice-agent

$COMPOSE ps
$COMPOSE logs --since=2m backend-api | grep -E 'brain_redis_connected|brain_redis_unavailable' | tail -5

$COMPOSE exec -T redis redis-cli EXISTS "interview:brain:${SESSION_ID}"
$COMPOSE exec -T redis redis-cli GET "interview:brain:${SESSION_ID}" | head -c 200 > /tmp/brain_after.txt
diff -u /tmp/brain_before.txt /tmp/brain_after.txt || true
```

**Pass:**

1. Backend logs `brain_redis_connected` after restart (not `brain_redis_unavailable`).
2. `EXISTS interview:brain:{session_id}` still `1`.
3. Payload still matches `session_id` (before/after fingerprint equal or only advanced by new turns).

**Optional stronger proof:** `$COMPOSE restart redis` (no volume wipe), then `EXISTS` still `1`. Recreating the Redis volume is **not** a continuity proof.

---

## 5. Rollback

1. Note current tag: `sudo cat "$APP/.last-successful-tag"`.  
2. Redeploy previous known-good SHA via `deploy.sh` (section 3).  
3. Confirm `$COMPOSE ps` healthy; re-check Redis `PING`.  
4. If Redis volume corruption suspected: stop API, `$COMPOSE stop redis`, restore from backup or recreate volume **only** after Mongo durable data is verified (Redis is hot cache, not source of truth).

---

## 6. Evidence checklist (paste into Azure 2092 / 2081)

- [ ] Date / operator  
- [ ] Image tag / commit SHA  
- [ ] `redis-cli ping` = PONG  
- [ ] Backend log shows `brain_redis_connected`  
- [ ] One full interview completed from this runbook  
- [ ] `EXISTS interview:brain:{session_id}` = 1 (or written exception)  
- [ ] **Restart continuity:** after `restart backend-api voice-agent`, key still `EXISTS` = 1 and `brain_redis_connected`  
- [ ] Rollback path exercised or documented  

When all boxes pass → move story **2092** and task **2081** to **Closed**.

---

## 7. Local/dev note (not staging acceptance)

Unset `REDIS_URL` → process-memory fallback (`put_hot_snapshot` returns `memory`).  
Unit coverage: `services/backend-api/tests/test_brain_state_store.py`.  
Local compose Redis is optional; staging Compose **includes** Redis as of this runbook.
