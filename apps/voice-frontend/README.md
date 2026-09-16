# Voice demo frontend

Internal Next.js demo and reference consumer for the Aaptor interviewer and
Racko customer-support workers. Shared voice behavior comes from
`packages/voice-ui`; production product frontends own their design and setup UX.

## Run locally

```powershell
cd ..\..
npm install
cd apps\voice-frontend
copy .env.example .env.local
npm run dev
```

Set `BACKEND_API_URL` in `.env.local` to the FastAPI service. It is server-only:
do not rename it to a `NEXT_PUBLIC_*` variable. The browser calls
`/api/sessions`; the Next.js server forwards an allowlisted, secret-free
payload to FastAPI.

Open http://localhost:3000 and choose a product.

## Checks

```powershell
npm run typecheck
npm run lint
npm test
npm run build
```
