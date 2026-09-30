---
kind: external_dependency
name: LiveKit — real-time voice session runtime
slug: livekit
category: external_dependency
category_hints:
    - framework_behavior
scope:
    - '**'
source_files:
    - services/voice-agent/aaptor_agent.py
    - services/voice-agent/racko_agent.py
    - packages/voice-ui/src/VoiceSession.tsx
    - apps/voice-frontend/package.json
    - services/backend-api/requirements.txt
---

### Role
LiveKit is the real-time audio/video transport layer: `livekit-agents` runs the voice worker (Aaptor/Racko) on Laptop 4, `livekit-client` + `@livekit/components-react` power the Next.js frontend, and `livekit-api` lets backend-api create rooms and manage sessions.

### Integration shape
- Worker entrypoints `aaptor_agent.py` / `racko_agent.py` register a named worker (`agent_name: aaptor`) with LiveKit; production uses `AgentSession` (not the deprecated `VoicePipelineAgent`).
- Frontend joins a room via `packages/voice-ui` which wraps `livekit-client` prejoin, room, media, controls, and flow primitives.
- Backend creates rooms and dispatches agents over HTTP; credentials come from `.env` (`LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET`).
- Production endpoints are tunneled through `livekit.gisul.co.in` (Cloudflare tunnel).

### Migration note
The README documents the migration path from livekit-agents 1.x `AgentSession` to later versions; do not revert to `VoicePipelineAgent`.