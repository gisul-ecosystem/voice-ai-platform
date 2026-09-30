---
kind: build_system
name: Monorepo Build, Docker Image Pipeline & Staging Deployment
category: build_system
scope:
    - '**'
source_files:
    - .github/workflows/ci.yml
    - deploy/deploy.sh
    - deploy/compose.staging.yml
    - deploy/Caddyfile
    - services/backend-api/Dockerfile
    - services/voice-agent/Dockerfile
    - services/context-engine/Dockerfile
    - apps/voice-frontend/Dockerfile
    - package.json
---

## Overview

The Voice AI Platform is a multi-service monorepo (Python FastAPI services, Next.js frontend, shared `packages/voice-ui`) built and deployed through GitHub Actions. There is no top-level Makefile; build orchestration lives in `.github/workflows/ci.yml`, per-service `Dockerfile`s, and the `deploy/` directory for staging rollout.

## CI Pipeline (`.github/workflows/ci.yml`)

- **Trigger**: runs on push to `dev` branch only.
- **Concurrency**: group `dev-staging-deployment`, `cancel-in-progress: false` — concurrent pushes are serialized.
- **Three-stage job graph**:
  1. `verify` — installs Python 3.12 venvs for both `services/backend-api` and `services/voice-agent`, runs `pytest -q` in each; sets up Node 22 and runs `npm ci && npm run frontend:check` (typecheck + lint + test + build) for the Next.js app.
  2. `images` — builds four Docker images via `docker/build-push-action`, tagging each with `${IMAGE_REGISTRY}/${service}:${GITHUB_SHA}` where `IMAGE_REGISTRY=ghcr.io/gisul-ecosystem`; uses GH Actions cache scoped per service (`backend-api`, `voice-agent`, `context-engine`, `voice-frontend`).
  3. `deploy-staging` — runs on a self-hosted runner labeled `self-hosted, linux, x64, voice-ai-staging`, environment `staging`, against URL `https://interviewer-dev.gisul.ai`. It copies `compose.staging.yml`, `Caddyfile`, and `deploy.sh` into `$HOME/voice-ai-platform/` then invokes `deploy.sh "${IMAGE_REGISTRY}" "${GITHUB_SHA}"`.

## Docker Images

Each service ships its own minimal image under `services/<name>/Dockerfile` (and `apps/voice-frontend/Dockerfile`):

- **Python services** (`backend-api`, `voice-agent`, `context-engine`): base `python:3.12-slim`, install deps with `pip install --only-binary=:all:` from `requirements.txt`, create a non-root `app` user/group, `chown -R app:app /app`, `EXPOSE` the service port, and `CMD` either `uvicorn main:app` or the agent entrypoint.
- **Next.js frontend** (`apps/voice-frontend/Dockerfile`): three-stage build using `node:22-bookworm-slim` — `dependencies` stage runs `npm ci --ignore-scripts` on just `package.json` files, `builder` stage copies source and runs `npm run build --workspace voice-frontend`, `runtime` stage copies `.next/standalone`, `.next/static`, and `public`, runs as non-root `nextjs:nodejs` user, exposes 3000, CMD `node apps/voice-frontend/server.js`.

Image tags are commit SHAs (immutable), never `latest`.

## Compose & Runtime Topology (`deploy/compose.staging.yml`)

Staging deploys six services plus two infra containers:

| Service | Image | Port | Healthcheck |
|---|---|---:|---|
| `mongo` | `mongo:8.0` | internal | `mongosh ping` |
| `redis` | `redis:7.4-alpine` | internal | `redis-cli ping` |
| `context-engine` | `${IMAGE_REGISTRY}/context-engine:${IMAGE_TAG}` | 5555 | HTTP `/health` |
| `backend-api` | `${IMAGE_REGISTRY}/backend-api:${IMAGE_TAG}` | 5554 (localhost-only) | JSON health asserting `mongo_connected` |
| `voice-agent` | `${IMAGE_REGISTRY}/voice-agent:${IMAGE_TAG}` | 8081 (localhost-only) | TCP socket check |
| `frontend` | `${IMAGE_REGISTRY}/voice-frontend:${IMAGE_TAG}` | 3000 (localhost-only) | HTTP `/` |
| `gateway` | `caddy:2.10-alpine` | 80/443 | — |

All services use a shared `x-logging` YAML anchor (`json-file`, max-size 10m, max-file 5). Secrets/env files live on disk at `/etc/voice-ai-platform/*.env` (mounted externally). External dependencies (`livekit.gisul.co.in`, `api.elevenlabs.io`) are pinned to IPs via `extra_hosts` because the staging VM DNS is unreliable.

## Deployment Script (`deploy/deploy.sh`)

- Enforced by `set -Eeuo pipefail`.
- Takes exactly two args: `<image-registry>` and `<image-tag>` (exit 64 otherwise).
- Uses `flock -n .deploy.lock` to prevent concurrent deployments (exit 75 if locked).
- Reads previous successful tag from `deploy/.last-successful-tag`.
- Performs `docker compose pull` then `up --detach --remove-orphans --force-recreate --wait --wait-timeout 240`.
- Health validation hits `http://127.0.0.1:3000/api/health` and `https://${PUBLIC_HOST}/interviewer` (with `--resolve` to bypass DNS).
- On success, writes new tag to `.last-successful-tag` and prunes images older than 168h.
- On failure, attempts an automatic rollback to the previous tag.

## Frontend Workspace Scripts (`package.json`)

Top-level `package.json` declares workspaces `["apps/voice-frontend", "packages/voice-ui"]` and provides:
- `frontend:dev` → `npm run dev --workspace voice-frontend`
- `frontend:check` → typecheck + lint + test + build for `voice-frontend` (the same sequence CI runs).

Per-app tooling is isolated: `apps/voice-frontend/vitest.config.ts` + `vitest.setup.ts` for tests, `eslint.config.mjs` for linting, `next.config.ts` for Next.js config.

## Versioning Strategy

- Images are tagged with `${GITHUB_SHA}` — immutable, reproducible artifacts pushed to `ghcr.io/gisul-ecosystem`.
- The deploy script tracks the last successful tag in `deploy/.last-successful-tag` and rolls back to it automatically on health-check failure.
- No semantic versioning manifest exists at repo root; versions flow through Git commits.

## Constraints Observed

- Only the `dev` branch triggers CI (enforced by workflow `on.push.branches`).
- All Python services run as non-root users inside their images (`USER app`).
- The frontend runs as non-root `nextjs` user.
- Services expose ports only bound to `127.0.0.1` in compose; Caddy is the sole public-facing gateway on 80/443.
- `pip install --only-binary=:all:` is used in every Python Dockerfile, enforcing binary-only dependency resolution.
- The `verify` job requires both Python services' pytest suites and the full frontend `frontend:check` gate to pass before any image is built.