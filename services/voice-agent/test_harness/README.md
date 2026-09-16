# Voice agent test frontend

Start either an Aaptor interview or a Racko customer-support session from the
browser. The page asks backend-api to create the LiveKit room, dispatch the
selected worker, and mint the participant token. No manual room creation or
token copying is needed.

## Prerequisites

Laptop 4 must be running the worker you want to test:

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

## 1. Start backend-api

```bash
cd services/backend-api
python -m uvicorn main:app --port 5554
```

## 2. Serve the frontend

Browsers block the microphone on `file://`.

```bash
cd services/voice-agent/test_harness
python -m http.server 8765
```

## 3. Join

Open `http://127.0.0.1:8765/index.html`, select AI Interviewer or Customer
Support, and begin the session. Interview-only JD/resume fields are hidden for
Customer Support. The token is kept in memory and is not added to the URL or
browser storage.

Allow the microphone and optional camera. You should hear the selected agent,
then speak a reply.

## If the agent never speaks

- Worker still running and still `registered worker`
- Page shows the selected agent as connected
- Mic permission granted; status line says `connected`
- LLM / STT / TTS / backend-api reachable (`GET http://localhost:5554/health/all` on Laptop 4)
