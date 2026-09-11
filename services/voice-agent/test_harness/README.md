# Voice-agent test harness

Talk to `aaptor_agent.py` over LiveKit without the candidate frontend. Mic in, agent audio out.

## Prerequisites

Laptop 4 already running the worker:

```bash
cd services/voice-agent
python aaptor_agent.py start
```

You want the log line `registered worker` with `url: wss://livekit.gisul.co.in`. Leave that process running.

STT (Laptop 2), TTS (Laptop 3), and LLM (Laptop 1) should be reachable, or the agent will join but fail on the first turn. Stage 1 also calls `POST {BACKEND_API_URL}/interviews/plan`; if the backend is down the agent falls back to a generic outline.

## 1. Mint a token (and set Stage 1 room metadata)

From `services/voice-agent`:

```bash
python test_harness/generate_token.py
```

This:

- Creates (or updates) a LiveKit room
- Sets room metadata to `{"job_description": "...", "resume_text": "..."}` — the same keys `aaptor_agent.py` already reads for Stage 1
- Prints `LIVEKIT_URL`, `ROOM`, `TOKEN`, and a browser join URL

JD / resume sources, first match wins per field:

| Source | How |
|---|---|
| CLI | `--job-description "..."` / `--resume-text "..."` |
| Files | `--job-file path` / `--resume-file path` |
| Env | `JOB_DESCRIPTION` / `RESUME_TEXT` in `services/voice-agent/.env` |
| Built-in sample | used if nothing else is set |

`.env` `LIVEKIT_TOKEN_TTL_MINUTES=2` is too short for a spoken test. The script defaults TTL to at least 30 minutes; override with `--ttl-minutes`.

```bash
python test_harness/generate_token.py --room aaptor-test-1 --ttl-minutes 60
python test_harness/generate_token.py --job-file ./jd.txt --resume-file ./resume.txt
```

## 2. Serve the HTML (do not use `file://`)

Browsers block the microphone on `file://`.

```bash
cd services/voice-agent/test_harness
python -m http.server 8765
```

## 3. Join

Open the `http://127.0.0.1:8765/index.html?...` URL printed by the token script, or open `http://127.0.0.1:8765/index.html` and paste URL + token into the form.

Allow the mic. You should hear the agent's opening question, then speak a reply. The worker log should show `session_start` then `stage1_outline` / `stage2_question`.

## If the agent never speaks

- Worker still running and still `registered worker`
- You joined the **same room name** the token was minted for
- Mic permission granted; status line says `connected`
- LLM / STT / TTS / backend-api reachable (`GET http://localhost:8000/health/all` on Laptop 4)
