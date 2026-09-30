---
kind: external_dependency
name: Redis — brain state cache and TTS cache
slug: redis
category: external_dependency
category_hints:
    - vendor_identity
scope:
    - '**'
source_files:
    - services/backend-api/db/redis_brain.py
    - services/model-serving/tts/requirements.txt
---

### Role
Two roles in this repo:
1. `services/backend-api/db/redis_brain.py` — hot cache for the interview 'brain' state (compiled question plan, scoring context) so the voice-agent can read it without hitting Mongo on every turn.
2. `services/model-serving/tts/` — Kokoro TTS service uses Redis as its output cache.

### Deployment
Local laptop deployment starts a standalone Redis container on port 6379 alongside the TTS service.