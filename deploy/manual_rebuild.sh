#!/usr/bin/env bash
# Manual staging rebuild when GitHub Actions / GHCR CI is unavailable.
# Run on the staging VM (10.110.50.10) after WireGuard + SSH.
#
# Usage:
#   sudo bash deploy/manual_rebuild.sh [branch] [image-tag]
# Examples:
#   sudo bash deploy/manual_rebuild.sh interviewer manual-$(date +%Y%m%d%H%M)
#   sudo bash deploy/manual_rebuild.sh interviewer ddb7d18
set -Eeuo pipefail

BRANCH="${1:-interviewer}"
IMAGE_TAG="${2:-manual-$(date -u +%Y%m%d%H%M%S)}"
IMAGE_REGISTRY="${IMAGE_REGISTRY:-local/voice-ai}"
APP="${APP:-/home/voiceai-runner/voice-ai-platform}"
SRC="${SRC:-$APP/src}"
PUBLIC_HOST="${INTERVIEWER_PUBLIC_HOST:-interviewer-dev.gisul.ai}"

echo "==> branch=${BRANCH} tag=${IMAGE_TAG} registry=${IMAGE_REGISTRY}"

if [[ ! -d "${SRC}/.git" ]]; then
  echo "cloning repo into ${SRC}"
  mkdir -p "$(dirname "${SRC}")"
  git clone https://github.com/gisul-ecosystem/voice-ai-platform.git "${SRC}"
fi

cd "${SRC}"
git fetch --all --prune
git checkout "${BRANCH}"
git pull --ff-only origin "${BRANCH}"

install -d -m 750 "${APP}"
install -m 640 "${SRC}/deploy/compose.staging.yml" "${APP}/compose.staging.yml"
install -m 640 "${SRC}/deploy/Caddyfile" "${APP}/Caddyfile"
install -m 750 "${SRC}/deploy/deploy.sh" "${APP}/deploy.sh"

echo "==> building images locally (no GHCR pull required)"
docker build -f services/context-engine/Dockerfile \
  -t "${IMAGE_REGISTRY}/context-engine:${IMAGE_TAG}" .
docker build -f services/backend-api/Dockerfile \
  -t "${IMAGE_REGISTRY}/backend-api:${IMAGE_TAG}" .
docker build -f services/voice-agent/Dockerfile \
  -t "${IMAGE_REGISTRY}/voice-agent:${IMAGE_TAG}" .
docker build -f apps/voice-frontend/Dockerfile \
  -t "${IMAGE_REGISTRY}/voice-frontend:${IMAGE_TAG}" .

export IMAGE_REGISTRY IMAGE_TAG
COMPOSE=(docker compose -f "${APP}/compose.staging.yml" --project-directory "${APP}")

echo "==> recreating stack"
docker rm -f voice-ai-platform-voice-agent-1 >/dev/null 2>&1 || true
"${COMPOSE[@]}" up --detach --remove-orphans --force-recreate --wait --wait-timeout 300

echo "==> health checks"
curl --fail --silent --show-error --max-time 10 --retry 10 --retry-delay 3 --retry-connrefused \
  "http://127.0.0.1:3000/api/health" >/dev/null
curl --fail --silent --show-error --max-time 10 --retry 10 --retry-delay 3 --retry-connrefused \
  --resolve "${PUBLIC_HOST}:443:127.0.0.1" \
  "https://${PUBLIC_HOST}/interviewer" >/dev/null

printf '%s' "${IMAGE_TAG}" >"${APP}/.last-successful-tag"
echo "==> healthy. tag=${IMAGE_TAG}"
"${COMPOSE[@]}" ps
echo "Check worker: ${COMPOSE[*]} logs --since=5m voice-agent | grep registered"
