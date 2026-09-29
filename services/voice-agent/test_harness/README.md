# Low-level LiveKit token utility

The maintained browser experience is now the Next.js application at
`apps/voice-frontend`. This folder contains only a developer CLI for manually
creating a LiveKit room and participant token when diagnosing worker behavior.

## Prerequisites

The selected worker must be running:

```bash
cd services/voice-agent
python aaptor_agent.py start
# Or, in a separate test:
python racko_agent.py start
```

You want the log line `registered worker` with `url: wss://livekit.gisul.co.in`. Leave that process running.

The backend must be running at `http://127.0.0.1:5554`. STT, TTS, and LLM must
also be reachable, or the agent will join but fail on the first turn. Stage 1
calls `POST {BACKEND_API_URL}/interviews/plan`; if its LLM fails, the agent uses
a generic outline.

Product behavior is implemented under `products/interviewer/` and
`products/customer_support/`. The root worker scripts are stable launch
wrappers over the shared `voice_platform/` runtime.

The utility reads LiveKit credentials from `services/voice-agent/.env`. Do not
commit its output or share generated tokens.

## Generate a token

```bash
cd services/voice-agent
python test_harness/generate_token.py --agent-name aaptor
```

Use `--help` for room, participant, context-file, and provider override options.
For normal browser testing, follow the frontend instructions in the repository
root README.

## If the agent never speaks

- Worker still running and still `registered worker`
- LLM / STT / TTS / backend-api reachable (`GET http://localhost:5554/health/all` on Laptop 4)
