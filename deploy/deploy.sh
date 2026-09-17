#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: deploy.sh <image-registry> <image-tag>" >&2
  exit 64
fi

IMAGE_REGISTRY="$1"
IMAGE_TAG="$2"
DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_FILE="${DEPLOY_DIR}/.last-successful-tag"
COMPOSE_FILE="${DEPLOY_DIR}/compose.staging.yml"

exec 9>"${DEPLOY_DIR}/.deploy.lock"
flock -n 9 || {
  echo "another deployment is already running" >&2
  exit 75
}

previous_tag=""
if [[ -f "${STATE_FILE}" ]]; then
  previous_tag="$(<"${STATE_FILE}")"
fi

deploy_tag() {
  local tag="$1"
  IMAGE_REGISTRY="${IMAGE_REGISTRY}" IMAGE_TAG="${tag}" \
    docker compose --file "${COMPOSE_FILE}" pull
  IMAGE_REGISTRY="${IMAGE_REGISTRY}" IMAGE_TAG="${tag}" \
    docker compose --file "${COMPOSE_FILE}" up \
      --detach --remove-orphans --wait --wait-timeout 240
}

echo "deploying image tag ${IMAGE_TAG}"
if deploy_tag "${IMAGE_TAG}" && curl --fail --silent --show-error \
  --retry 10 --retry-delay 3 --retry-connrefused \
  "http://127.0.0.1:3000/" >/dev/null; then
  printf '%s' "${IMAGE_TAG}" >"${STATE_FILE}"
  docker image prune --force --filter "until=168h" >/dev/null
  echo "deployment ${IMAGE_TAG} is healthy"
  exit 0
fi

echo "deployment ${IMAGE_TAG} failed" >&2
if [[ -n "${previous_tag}" && "${previous_tag}" != "${IMAGE_TAG}" ]]; then
  echo "rolling back to ${previous_tag}" >&2
  deploy_tag "${previous_tag}"
  printf '%s' "${previous_tag}" >"${STATE_FILE}"
fi
exit 1
