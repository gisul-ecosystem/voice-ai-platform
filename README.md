# Voice AI Platform — 4-Laptop Pilot Topology

Aaptor v2 (AI Interviewer) + Racko-style Voice CS. Research/pilot stage running
across 4 laptops (RTX 4060 8GB each), one component per laptop, communicating
over LAN via HTTP. Designed to swap to real GPU servers later with zero code
changes — only `.env` URLs and the LLM backend (Ollama -> vLLM) change.

## Laptop assignment

| Laptop | Runs | Port |
|---|---|---|
| 1 | LLM - Ollama serving Qwen3-4B | 11434 |
| 2 | STT - Nemotron 3.5 ASR (NeMo) wrapped in FastAPI | 5552 |
| 3 | TTS - Kokoro-82M wrapped in FastAPI, + Redis | 5553 / 6379 |
| 4 | backend-api (FastAPI) + voice-agent (LiveKit worker) + MongoDB | 5554 |

Run **only the service that laptop is assigned**. Use **Python 3.11**. On Windows,
allow inbound TCP for that laptop's port (11434 / 5552 / 5553 / 5554). Redis stays
6379; Mongo stays 27017. Ollama stays on its default **11434** — do not move it
to 5551.

## Clone (every laptop)

```powershell
git clone https://github.com/gisul-ecosystem/voice-ai-platform.git
cd voice-ai-platform
```

Each service reads the other laptops' LAN IPs from its own `.env`. Copy
`.env.example` to `.env` in each service folder and fill in real IPs
(e.g. `192.168.1.11`). Do **not** commit `.env` files; they are gitignored.

---

## Laptop 1 — LLM (Ollama, no pip for the model)

Install [Ollama](https://ollama.com/download). The model tag is
`qwen3:4b-instruct-2507-q8_0` — **not** `qwen3:4b-instruct-q8_0`.

```powershell
ollama pull qwen3:4b-instruct-2507-q8_0
ollama serve
```

Linux/macOS alternative: `cd services/model-serving/llm` then `./run_ollama.sh`.

Health:

```powershell
curl http://localhost:11434/api/tags
```

If you keep a hosted OpenAI-compatible LLM instead, skip this laptop and set
`LLM_SERVICE_URL` / `LLM_MODEL_NAME` on Laptop 4 (example:
`https://llm.gisul.ai/v1` with `qwen3:4b-instruct-2507-q4_K_M`).

---

## Laptop 2 — STT (Nemotron 3.5 ASR)

First start downloads `nvidia/nemotron-3.5-asr-streaming-0.6b` from Hugging Face.
Needs a CUDA GPU and CUDA-enabled PyTorch.

```powershell
cd services\model-serving\stt
pip uninstall torch torchvision torchaudio -y
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app:app --host 0.0.0.0 --port 5552
```

Install `torch`, `torchvision`, and `torchaudio` from the **same** CUDA index. If NeMo pulls a mismatched `torchvision`, startup fails with `RuntimeError: operator torchvision::nms does not exist`.

Health:

```powershell
curl http://localhost:5552/health
```

`target_lang` is required on `.transcribe()` (the wrapper already passes `"auto"`).

---

## Laptop 3 — TTS (Kokoro-82M)

Kokoro often needs **espeak-ng** installed on the OS. Voice is American English
`af_heart`. Kokoro has **no** native Indian-accented English (`hf_*` is Hindi,
a different language). CosyVoice 2 is unimplemented until built and tested.

```powershell
cd services\model-serving\tts
pip install -r requirements.txt
copy .env.example .env
docker run -d -p 6379:6379 redis
python -m uvicorn app:app --host 0.0.0.0 --port 5553
```

Health:

```powershell
curl http://localhost:5553/health
curl -X POST http://localhost:5553/synthesize -H "Content-Type: application/json" -d "{\"text\":\"Hello candidate\"}" --output out.wav
```

Until this laptop answers on `:5553`, the agent can join a LiveKit room and
generate text but will not speak.

---

## Laptop 4 — backend-api + voice-agent

### backend-api

```powershell
cd services\backend-api
pip install -r requirements.txt
copy .env.example .env
# edit .env: STT/TTS LAN IPs, LLM URL, LiveKit keys, Mongo
# skip the cd if the prompt is already ...\services\backend-api
python -m uvicorn main:app --host 0.0.0.0 --port 5554
```

### voice-agent (new terminal)

```powershell
cd services\voice-agent
pip install -r requirements.txt
copy .env.example .env
# same IPs + LiveKit
python aaptor_agent.py start
```

Use `python aaptor_agent.py start` — not `python main.py`. You want the log line
`registered worker` with `agent_name: aaptor`.

Point `services/voice-agent/.env` (and backend `.env`) at the other laptops:

```
LLM_SERVICE_URL=http://192.168.1.11:11434/v1
STT_SERVICE_URL=http://192.168.1.12:5552
TTS_SERVICE_URL=http://192.168.1.13:5553
BACKEND_API_URL=http://localhost:5554
LLM_MODEL_NAME=qwen3:4b-instruct-2507-q8_0
```

Hosted LLM instead of Laptop 1:

```
LLM_SERVICE_URL=https://llm.gisul.ai/v1
LLM_MODEL_NAME=qwen3:4b-instruct-2507-q4_K_M
```

### Voice agent test frontend

Backend and the selected Aaptor or Racko worker must already be running:

```powershell
cd services\voice-agent\test_harness
python -m http.server 8765
```

Open **http://127.0.0.1:8765/index.html** (not `file://`), select AI Interviewer
or Customer Support, and begin the session. The frontend calls backend-api to
create the room, dispatch the selected worker, and mint the token automatically.
Details: `services/voice-agent/test_harness/README.md`.

---

## Phase 0 status (as of 2026-09-14)

**Built:** Stage 1 plan endpoint, Stage 2 live question generation via
`AgentSession`, retry-wrapped HTTP clients, `/health` + `/health/all`, and an
integrated two-agent test frontend for room creation, camera/mic input, and
agent audio.

**Proved (last week):** LiveKit join works, hosted LLM responds
(`qwen3:4b-instruct-2507-q4_K_M`), STT transcribes correctly via
`https://voicestt.gisul.ai` (see `services/model-serving/stt/app.py` for
Windows temp-file and `en-US` prompt-key fixes).

**Not done:** TTS never tunneled (`https://voicetts.gisul.ai`) -- the agent
cannot speak yet; this is the blocker for a real end-to-end test. No production
candidate frontend. Mongo intermittently down (Stage 1 has a fallback).
CosyVoice, vLLM production, frontends -- out of scope for this phase.

**Tunnels:** only **gisul.ai** (and LiveKit on `livekit.gisul.co.in`). Do
not use any other Cloudflare account for STT/TTS.

**Ops:** an early git push included `.env` with LiveKit keys. Rotate
`LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` and confirm history is scrubbed
before the repo is treated as public. Rotation is **not** confirmed here.

**Inconsistency:** laptop Ollama is `qwen3:4b-instruct-2507-q8_0`; hosted
is `qwen3:4b-instruct-2507-q4_K_M`. Do not compare those two directly.

**Next:** STT/LLM tunnels back up -> TTS on 5553 / `voicetts.gisul.ai` ->
backend 5554 + worker on Laptop 4 -> harness join -> first real
end-to-end "hear question, speak, get next question" test.

---

## Migration path to real GPU servers (later, no redesign)

1. Replace Ollama (Laptop 1) with vLLM on the GPU server - same
   OpenAI-compatible `/v1/chat/completions` interface, so `voice-agent`'s
   `llm_client.py` needs zero changes, only the URL in `.env`.
   vLLM structured output param is `structured_outputs` (not deprecated
   `guided_json`). Qwen3-family: prefer AWQ over GPTQ.
2. Optionally co-locate STT+TTS+LLM on one GPU box once VRAM allows - same
   FastAPI wrapper services, just pointed at localhost instead of a LAN IP.
3. Split into isolated Aaptor/CS pools once concurrency justifies it (see
   `docs/production_architecture_context.md`).

See `docs/implementation_plan.md` for the full phased roadmap and sprint plan.
Current status is **Phase 0**. livekit-agents 1.x uses `AgentSession` (not the
deprecated `VoicePipelineAgent` API).
