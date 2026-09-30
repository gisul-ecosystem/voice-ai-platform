#!/usr/bin/env bash
set -euo pipefail
APP=/home/voiceai-runner/voice-ai-platform
TAG="$(cat "$APP/.last-successful-tag")"
export IMAGE_REGISTRY=local/voice-ai
export IMAGE_TAG="$TAG"
echo "using ${IMAGE_REGISTRY}/${IMAGE_TAG}"
docker compose -f "$APP/compose.staging.yml" --project-directory "$APP" \
  up -d --force-recreate --no-deps backend-api voice-agent
docker compose -f "$APP/compose.staging.yml" --project-directory "$APP" \
  ps backend-api voice-agent
echo "--- voice-agent registration ---"
sleep 8
docker logs --since=1m voice-ai-platform-voice-agent-1 2>&1 | grep -E 'registered worker|inference_overrides|tts_provider|ERROR' | tail -20 || true
echo "--- health ---"
curl -sS -o /dev/null -w "frontend_health=%{http_code}\n" http://127.0.0.1:3000/api/health
curl -sS -o /dev/null -w "interviewer_page=%{http_code}\n" \
  --resolve interviewer-dev.gisul.ai:443:127.0.0.1 \
  https://interviewer-dev.gisul.ai/interviewer
