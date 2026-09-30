---
kind: dependency_management
name: 'Monorepo Dependency Management: npm Workspaces + Per-Service requirements.txt'
category: dependency_management
scope:
    - '**'
source_files:
    - package.json
    - package-lock.json
    - apps/voice-frontend/package.json
    - packages/voice-ui/package.json
    - services/backend-api/requirements.txt
    - services/backend-api/requirements-dev.txt
    - services/voice-agent/requirements.txt
    - services/voice-agent/requirements-dev.txt
    - services/context-engine/requirements.txt
    - services/model-serving/stt/requirements.txt
    - services/model-serving/tts/requirements.txt
    - .github/workflows/ci.yml
---

# Dependency Management in Voice AI Platform

## Approach Overview

This monorepo uses two independent package managers, one per language family:

- **Node.js / TypeScript**: npm workspaces at the repository root, with a shared `package.json` declaring workspace members and a lockfile (`package-lock.json`).
- **Python**: Per-service `requirements.txt` files (with optional `requirements-dev.txt` for test-only deps), installed into isolated virtual environments.

There is no vendoring of Python packages, no `pyproject.toml`, no Poetry/Pipenv, no private PyPI registry configured, and no Node.js private registry or `.npmrc`. Dependencies are resolved from the public registries (npmjs.org and pypi.org).

## Key Files

| Area | Manifest(s) | Role |
|---|---|---|
| Root (workspaces) | `package.json` | Declares `workspaces: ["apps/voice-frontend", "packages/voice-ui"]`; pins top-level React 19.2.8; exposes `frontend:dev` / `frontend:check` scripts that delegate to the app workspace via `--workspace voice-frontend`. |
| Frontend app | `apps/voice-frontend/package.json` | Next.js 16.3.5 app; depends on `@gisul/voice-ui` via a local `file:` reference, plus LiveKit client libraries and Vitest/Eslint/TypeScript tooling. |
| Shared UI package | `packages/voice-ui/package.json` | Private npm package `@gisul/voice-ui` v0.1.0; declares `peerDependencies` on `@livekit/components-react ^2.9.0`, `livekit-client ^2.22.0`, and `react >=18 <20`; exports `.` and `./session`. |
| Backend API | `services/backend-api/requirements.txt`, `requirements-dev.txt` | FastAPI 0.115.6, uvicorn 0.34.0, motor/pymongo, pydantic 2.10.4, httpx 0.27.0, livekit-api 1.2.1, redis 5.2.1, cryptography 42.0.8; dev adds pytest 8.4.2 + pytest-asyncio 0.26.0. |
| Voice agent | `services/voice-agent/requirements.txt`, `requirements-dev.txt` | livekit-agents 1.8.1, silero plugin, httpx 0.27.0, tenacity, websockets 15.0.1. |
| Context engine | `services/context-engine/requirements.txt` | Minimal FastAPI/uvicorn stack. |
| STT service | `services/model-serving/stt/requirements.txt` | Uses `nemo_toolkit[asr]`; pinned versions are intentionally omitted because CUDA wheels must be installed first from `https://download.pytorch.org/whl/cu124` (see inline comment). |
| TTS service | `services/model-serving/tts/requirements.txt` | FastAPI + kokoro + soundfile + redis. |
| CI | `.github/workflows/ci.yml` | Orchestrates dependency installation and verification across all services. |

## Architecture and Conventions

### Node.js (npm workspaces)

- The root `package.json` is `private: true` and acts as the workspace root. It pins `react` and `react-dom` to exact version `19.2.8` so both the app and the shared `@gisul/voice-ui` package resolve the same React instance.
- The shared package `@gisul/voice-ui` is consumed by the frontend via a local filesystem reference (`"@gisul/voice-ui": "file:../../packages/voice-ui"`) rather than being published to npm. Its `exports` map exposes only `.` and `./session`, constraining the public surface.
- `peerDependencies` on `react`, `@livekit/components-react`, and `livekit-client` in the shared package force the consuming app to provide compatible versions — this avoids bundling duplicate copies of React/LiveKit.
- The root script `frontend:check` chains typecheck → lint → test → build for the workspace, which is what CI runs.
- A single `package-lock.json` at the repo root records the full resolved tree for the workspace.

### Python (per-service requirements.txt)

- Each service under `services/` has its own `requirements.txt` listing runtime dependencies with explicit pinning (e.g. `fastapi==0.115.6`, `httpx==0.27.0`, `websockets==15.0.1`).
- Test-only dependencies live in a sibling `requirements-dev.txt` that re-includes the runtime file via `-r requirements.txt` and then adds `pytest==8.4.2` and `pytest-asyncio==0.26.0`.
- The STT service's `requirements.txt` deliberately omits pinned versions for `fastapi`, `uvicorn`, `python-multipart`, and `nemo_toolkit[asr]` because it requires a pre-installed matching CUDA wheel from `https://download.pytorch.org/whl/cu124`; the file's header comments document the required install order.
- There is no `requirements.in` / `pip-tools`, no `Pipfile`, no `pyproject.toml`, and no lockfile committed alongside the manifests.

### CI-driven installation

The GitHub Actions workflow `.github/workflows/ci.yml` is the authoritative source for how dependencies are installed in CI:

- Python: `actions/setup-python@v7` with `python-version: "3.12"`, pip cache keyed on `services/backend-api/requirements*.txt` and `services/voice-agent/requirements*.txt`. It creates a separate `.venv-backend` and `.venv-agent` virtual environment and installs each service's `requirements.txt` + `requirements-dev.txt` before running `pytest -q`.
- Node: `actions/setup-node@v7` with `node-version: "22"`, npm cache enabled, then `npm ci` followed by `npm run frontend:check`.
- Docker images are built for all four services and pushed to `ghcr.io/gisul-ecosystem` with tags based on `${GITHUB_SHA}`; deployment pulls these immutable images.

## Conventions and Constraints

- **Runtime vs. dev dependencies are separated** in Python via `-r requirements.txt` inclusion in `requirements-dev.txt` (enforced by convention; both backend-api and voice-agent follow this pattern).
- **Python dependencies are pinned with `==`** in `requirements.txt` files (backend-api, voice-agent, context-engine); the STT service is an exception documented in its file header.
- **Node dependencies use caret ranges (`^`) for most packages**, but React itself is pinned to an exact version (`19.2.8`) at the workspace root to guarantee a single copy across the workspace.
- **Shared code between the frontend and other parts of the repo is distributed as a local npm workspace** (`@gisul/voice-ui`) referenced via `file:` — not published to a registry.
- **Peer dependencies are declared** in the shared package to prevent accidental duplication of React/LiveKit bundles.
- **CI pins tool versions explicitly** (setup-python v7.0.0, setup-node v7.0.0, actions/checkout v7.0.1, docker/build-push-action v7.4.0) rather than using floating tags.
- **No private registries or vendoring are configured** — there is no `.npmrc`, no `PYPI_URL`/`PIP_INDEX_URL`, no `vendor/` directory, and no `go.mod`/`go.sum`.
- **Dockerfiles are used for containerized builds** of each service, and the CI workflow references them directly (`services/backend-api/Dockerfile`, `services/voice-agent/Dockerfile`, `services/context-engine/Dockerfile`, `apps/voice-frontend/Dockerfile`).