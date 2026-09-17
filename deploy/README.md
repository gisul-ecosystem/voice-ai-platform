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

The stack contains MongoDB, the context engine, backend API, interviewer worker,
reference frontend, and Caddy gateway. Only ports 80 and 443 are externally
bound. Backend and worker health ports bind to loopback.

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

The private IP cannot receive a public ACME certificate. Caddy therefore issues
an internal certificate for `https://10.110.50.10`. Test devices must trust the
Caddy root certificate before microphone APIs will work:

```bash
docker compose -f "$HOME/voice-ai-platform/compose.staging.yml" \
  cp gateway:/data/caddy/pki/authorities/local/root.crt /tmp/voice-ai-staging-root.crt
```

Install that certificate only on managed staging devices. Replace the IP and
internal CA with an approved DNS name and certificate before public access.

## Operations

Inspect status:

```bash
docker compose -f "$HOME/voice-ai-platform/compose.staging.yml" ps
```

Inspect service logs:

```bash
docker compose -f "$HOME/voice-ai-platform/compose.staging.yml" logs --since=15m SERVICE
```

Redeploy a known commit:

```bash
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io --username USER --password-stdin
"$HOME/voice-ai-platform/deploy.sh" ghcr.io/gisul-ecosystem COMMIT_SHA
docker logout ghcr.io
```

The deploy script serializes deployments with a file lock and records the last
healthy image tag in `$HOME/voice-ai-platform/.last-successful-tag`.
