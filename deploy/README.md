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

## Self-hosted runner (always on)

On the staging VM (`10.110.50.10`), the runner lives at `/opt/actions-runner`
and runs as systemd unit
`actions.runner.gisul-ecosystem-voice-ai-platform.voice-ai-staging.service`
(user `voiceai-runner`). It is **enabled** and uses a drop-in
`always-on.conf` with `Restart=always` / `RestartSec=10` so the process
survives crashes and reboots.

```bash
sudo systemctl status actions.runner.gisul-ecosystem-voice-ai-platform.voice-ai-staging.service
sudo journalctl -u actions.runner.gisul-ecosystem-voice-ai-platform.voice-ai-staging.service -n 50 --no-pager
```

GitHub shows the runner **offline** when the VM cannot reach Actions egress
(`*.actions.githubusercontent.com:443` and public DNS). Local LAN to
`10.110.0.1` / `10.110.0.10` can still work while outbound HTTPS/DNS is
broken — fix NAT/firewall on the gateway, then restart the unit if needed.
A local `active (running)` service alone is not enough.

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
2. Staging currently keeps the existing LiveKit credentials via
   `LIVEKIT_ALLOW_WEAK_API_KEY=true` in Compose (same key/secret in
   `/etc/voice-ai-platform/backend-api.env` and `voice-agent.env`).
3. After changing agent name or keys: redeploy / recreate those two containers
   and confirm logs show `registered worker` with `agent_name=aaptor-staging`.


## LiveKit / ElevenLabs DNS pin (staging VM)

If containers cannot resolve public names (host DNS broken), Compose pins:

- `livekit.gisul.co.in` → `103.99.38.226`
- `api.elevenlabs.io` → `34.8.184.191` (voice-agent only; re-resolve after DNS changes)

DNS pins do **not** replace outbound NAT. If the VM cannot reach those IPs on
`:443`, greeting/TTS and LiveKit still fail until gateway egress is restored.

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
