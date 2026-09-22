#!/usr/bin/env bash
# Staging Redis brain hot-memory proof (Azure 2092 / Task 2081).
# Run on the staging VM over WireGuard SSH.
#
# Usage:
#   APP=/home/voiceai-runner/voice-ai-platform
#   SESSION_ID=ses_... bash deploy/scripts/staging_redis_brain_proof.sh
#   SESSION_ID=ses_... PROVE_RESTART=1 bash deploy/scripts/staging_redis_brain_proof.sh

set -euo pipefail

APP="${APP:-/home/voiceai-runner/voice-ai-platform}"
COMPOSE="${COMPOSE:-sudo docker compose -f $APP/compose.staging.yml --project-directory $APP}"
SESSION_ID="${SESSION_ID:-}"
PROVE_RESTART="${PROVE_RESTART:-0}"
KEY_PREFIX="interview:brain:"

if [[ -z "$SESSION_ID" ]]; then
  echo "SESSION_ID is required (from a live/recent interview)."
  echo "Example: SESSION_ID=ses_abc123 $0"
  exit 2
fi

KEY="${KEY_PREFIX}${SESSION_ID}"

echo "== stack =="
$COMPOSE ps
echo

echo "== redis ping =="
$COMPOSE exec -T redis redis-cli ping
echo

echo "== backend redis connectivity (recent logs) =="
$COMPOSE logs --since=15m backend-api 2>/dev/null \
  | grep -E 'brain_redis_connected|brain_redis_unavailable|brain_redis_write_failed' \
  | tail -20 || true
echo

echo "== hot key proof for ${KEY} =="
EXISTS=$($COMPOSE exec -T redis redis-cli EXISTS "$KEY" | tr -d '\r')
TTL=$($COMPOSE exec -T redis redis-cli TTL "$KEY" | tr -d '\r')
echo "EXISTS=${EXISTS}"
echo "TTL=${TTL}"
$COMPOSE exec -T redis redis-cli GET "$KEY" | head -c 400
echo
echo

if [[ "$EXISTS" != "1" ]]; then
  echo "FAIL: hot brain key missing. Complete 2-3 live turns first, then re-run."
  exit 1
fi
if [[ "$TTL" -le 0 ]]; then
  echo "FAIL: TTL must be > 0 (got ${TTL})."
  exit 1
fi

if [[ "$PROVE_RESTART" == "1" ]]; then
  echo "== restart continuity (§4.5) =="
  $COMPOSE exec -T redis redis-cli GET "$KEY" | head -c 200 > /tmp/brain_before.txt
  $COMPOSE restart backend-api voice-agent
  sleep 8
  $COMPOSE ps
  $COMPOSE logs --since=2m backend-api 2>/dev/null \
    | grep -E 'brain_redis_connected|brain_redis_unavailable' \
    | tail -10 || true
  EXISTS_AFTER=$($COMPOSE exec -T redis redis-cli EXISTS "$KEY" | tr -d '\r')
  $COMPOSE exec -T redis redis-cli GET "$KEY" | head -c 200 > /tmp/brain_after.txt
  echo "EXISTS_AFTER=${EXISTS_AFTER}"
  diff -u /tmp/brain_before.txt /tmp/brain_after.txt || true
  if [[ "$EXISTS_AFTER" != "1" ]]; then
    echo "FAIL: key missing after API/worker restart."
    exit 1
  fi
  echo "PASS: restart continuity"
fi

echo
echo "PASS: Redis hot brain proof for ${SESSION_ID}"
echo "Paste into Azure 2092 / 2081 evidence checklist."
