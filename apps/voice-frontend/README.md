# Voice demo frontend

Internal Next.js demo and reference consumer for the Aaptor interviewer and
Racko customer-support workers. Shared voice behavior comes from
`packages/voice-ui`; production product frontends own their design and setup UX.

## Run locally (full interviewer stack)

Use **three terminals** from the repo root (`voice-ai-platform`). Fill
`services/backend-api/.env` and `services/voice-agent/.env` first (copy from
`.env.example` if needed). Mongo must be reachable for the API.

### Terminal 1 — backend API

```powershell
cd services\backend-api
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m uvicorn main:app --reload --host 127.0.0.1 --port 5554
```

### Terminal 2 — interviewer voice agent

```powershell
cd services\voice-agent
python -m pip install -r requirements.txt -r requirements-dev.txt
python aaptor_agent.py start
```

Confirm logs show `registered worker` (local default agent name is usually
`aaptor`). For staging isolation use `LIVEKIT_AGENT_NAME=aaptor-staging`.

### Terminal 3 — frontend

```powershell
cd c:\Gisul\voice-ai-platform
npm install
cd apps\voice-frontend
copy .env.example .env.local
npm run dev
```

Or from the monorepo root:

```powershell
npm run frontend:dev
```

In `.env.local`, set `BACKEND_API_URL` to the FastAPI service (e.g.
`http://127.0.0.1:5554`). It is server-only — do not use a `NEXT_PUBLIC_*`
name. The browser calls `/api/*`; Next.js forwards to FastAPI.

Open http://localhost:3000/interviewer

**Wizard path (topics / alignment page):**

1. http://localhost:3000/interviewer/admin/design — role + JD → Generate  
2. http://localhost:3000/interviewer/admin/review — edit competencies / topics → Publish  
3. http://localhost:3000/interviewer/admin/invite — create candidate invite  

## Checks

```powershell
npm run typecheck
npm run lint
npm test
npm run build
```

From monorepo root:

```powershell
npm run frontend:check
```

Backend / agent unit tests:

```powershell
cd services\backend-api
python -m pytest -q

cd ..\voice-agent
python -m pytest -q
```

## Staging

With WireGuard connected: https://interviewer-dev.gisul.ai/interviewer  
Same wizard URLs under `/interviewer/admin/design` → `review` → `invite`.
