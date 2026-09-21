# Staging deployment

The `dev` branch is deployed to the private staging VM after all Python and
frontend CI jobs pass.

## Architecture

1. GitHub-hosted runners execute tests and build immutable container images.
2. Images are pushed to `ghcr.io/gisul-ecosystem` with the commit SHA as tag.
3. The repository-scoped `voice-ai-staging` runner executes only the deployment
   job on the VM.
4. Docker Compose pulls the images and waits for service health checks.
5. A failed update automatically attempts to restore the last successful tag.

The stack contains MongoDB, **Redis (hot interview brain)**, the context engine, backend API, interviewer worker,
reference frontend, and Caddy gateway. Only ports 80 and 443 are externally
bound. Backend and worker health ports bind to loopback.

For the operator checklist (start order, Redis key proof, rollback, Azure 2092
acceptance), see **`docs/staging_runbook_redis_brain.md`**.

## LiveKit worker isolation

Staging Compose sets `LIVEKIT_AGENT_NAME=aaptor-staging` on **backend-api** and
**voice-agent**. Local workers usually register as `aaptor`. If both use the same
LiveKit project (`LIVEKIT_URL` / API key), a local worker can steal staging jobs
and the staging agent stays silent.

Rules:

1. Stop local `voice-agent` when testing staging, **or** keep staging on
   `aaptor-staging`.
2. Do **not** use LiveKit `devkey` on staging. Put real API key/secret in
   `/etc/voice-ai-platform/backend-api.env` and `voice-agent.env`. Production
   and staging startup **reject** weak/shared keys (`devkey`, `dev`, `test`,
   `changeme`) with no override.
3. After changing agent name or keys: redeploy / recreate those two containers
   and confirm logs show `registered worker` with `agent_name=aaptor-staging`.

## VM secret files

Secrets are installed outside the checkout:

- `/etc/voice-ai-platform/backend-api.env`
- `/etc/voice-ai-platform/voice-agent.env`
- `/etc/voice-ai-platform/frontend.env`
- `/etc/voice-ai-platform/mongo.env`

They must be owned by `root:voiceai-runner`, mode `0640`, inside a mode `0750`
directory. Never add these files to Git or GitHub Actions output.

Required relationships:

- Frontend and backend use the same `BACKEND_SERVICE_TOKEN`.
- Worker and backend use the same `VOICE_AGENT_SERVICE_TOKEN`.
- Backend and worker use the same LiveKit deployment credentials.
- OpenAI is required by both backend planning and the worker LLM.
- Sarvam and ElevenLabs keys are required by the configured worker providers.

## HTTPS for browser audio

Use `https://interviewer-dev.gisul.ai` while connected to WireGuard. The
Cloudflare record is DNS-only and resolves to private IP `10.110.50.10`.
Caddy reads the Let's Encrypt certificate from
`/etc/letsencrypt/live/interviewer-dev.gisul.ai/`.

Do not use HTTPS through the raw private IP; browser TLS validation requires
the hostname.

## Operations

Staging checkout lives at `/home/voiceai-runner/voice-ai-platform` (not
`gisuladmin`'s home). Prefer:

```bash
APP=/home/voiceai-runner/voice-ai-platform
COMPOSE="sudo docker compose -f $APP/compose.staging.yml --project-directory $APP"
```

Inspect status:

```bash
$COMPOSE ps
```

Inspect service logs:

```bash
$COMPOSE logs --since=15m SERVICE
```

Redeploy a known commit:

```bash
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io --username USER --password-stdin
sudo "$APP/deploy.sh" ghcr.io/gisul-ecosystem COMMIT_SHA
docker logout ghcr.io
```

The deploy script serializes deployments with a file lock and records the last
healthy image tag in `$APP/.last-successful-tag`.

Redis brain acceptance (ping, interview key, restart continuity):  
`docs/staging_runbook_redis_brain.md`.
